-- Esquema de producción para Caza Cuotas en Supabase (PostgreSQL + Row Level Security)
-- Bloquea todo acceso anónimo: solo usuarios autenticados pueden ver partidos, favoritos y apuestas.

create table if not exists public.radar_snapshots (
  id int primary key default 1,
  generated_col text not null,
  scan_json jsonb not null,
  report_json jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.radar_snapshots enable row level security;
drop policy if exists "Authenticated users can read radar" on public.radar_snapshots;
create policy "Authenticated users can read radar"
  on public.radar_snapshots for select
  to authenticated using (true);

create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null,
  stake_mode text not null default 'flat',
  fib_step int not null default 0,
  bankroll_base numeric not null default 100.0,
  created_at timestamptz not null default now()
);
alter table public.user_profiles enable row level security;
drop policy if exists "Users manage own profile" on public.user_profiles;
create policy "Users manage own profile"
  on public.user_profiles for all
  to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

create table if not exists public.user_favorites (
  user_id uuid not null references auth.users(id) on delete cascade,
  event_id text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, event_id)
);
alter table public.user_favorites enable row level security;
drop policy if exists "Users manage own favorites" on public.user_favorites;
create policy "Users manage own favorites"
  on public.user_favorites for all
  to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

create table if not exists public.user_bets (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  match_date text not null,
  league text not null,
  event_id text not null,
  title text not null,
  market text not null,
  market_name text not null,
  odds numeric not null,
  stake_u numeric not null,
  legs_json jsonb not null,
  status text not null default 'PENDING',
  profit_u numeric not null default 0.0,
  settled_at timestamptz,
  result_note text
);
alter table public.user_bets enable row level security;
drop policy if exists "Users read own bets" on public.user_bets;
create policy "Users read own bets"
  on public.user_bets for select
  to authenticated using (auth.uid() = user_id);
drop policy if exists "Users insert own pending bets" on public.user_bets;
create policy "Users insert own pending bets"
  on public.user_bets for insert
  to authenticated with check (auth.uid() = user_id and status = 'PENDING');

-- v2: Admin role, internal Telegram-style Channel feed (Realtime + RLS) & Web Push Subscriptions
alter table public.user_profiles add column if not exists is_admin boolean not null default false;

create table if not exists public.channel_posts (
  id bigserial primary key,
  post_key text unique not null,
  created_at timestamptz not null default now(),
  kind text not null default 'match',
  title text not null,
  body_html text not null,
  image_data text,
  author_name text not null default 'Caza Cuotas'
);
alter table public.channel_posts enable row level security;
drop policy if exists "Authenticated users read channel" on public.channel_posts;
create policy "Authenticated users read channel"
  on public.channel_posts for select
  to authenticated using (true);
drop policy if exists "Admins insert channel posts" on public.channel_posts;
create policy "Admins insert channel posts"
  on public.channel_posts for insert
  to authenticated with check (
    exists (select 1 from public.user_profiles p where p.user_id = auth.uid() and p.is_admin = true)
  );
drop policy if exists "Admins delete channel posts" on public.channel_posts;
create policy "Admins delete channel posts"
  on public.channel_posts for delete
  to authenticated using (
    exists (select 1 from public.user_profiles p where p.user_id = auth.uid() and p.is_admin = true)
  );

create table if not exists public.push_subscriptions (
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, endpoint)
);
alter table public.push_subscriptions enable row level security;
drop policy if exists "Users manage own push subscriptions" on public.push_subscriptions;
create policy "Users manage own push subscriptions"
  on public.push_subscriptions for all
  to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

do $$
begin
  alter publication supabase_realtime add table public.channel_posts;
exception when duplicate_object then
  null;
end $$;

-- v3: Admin RPC to list registered users & activity safely (accessible ONLY when is_admin = true)
create or replace function public.admin_list_users()
returns table (
  user_id uuid,
  email text,
  display_name text,
  is_admin boolean,
  stake_mode text,
  bankroll_base numeric,
  created_at timestamptz,
  last_sign_in_at timestamptz,
  total_bets bigint,
  pending_bets bigint,
  net_profit_u numeric
)
language plpgsql
security definer
set search_path = public, auth
as $$
begin
  if not exists (
    select 1 from public.user_profiles p
    where p.user_id = auth.uid() and p.is_admin = true
  ) then
    raise exception 'Forbidden: admin access required';
  end if;

  return query
  select
    u.id as user_id,
    u.email::text,
    coalesce(p.display_name, split_part(u.email::text, '@', 1)) as display_name,
    coalesce(p.is_admin, false) as is_admin,
    coalesce(p.stake_mode, 'flat') as stake_mode,
    coalesce(p.bankroll_base, 100.0) as bankroll_base,
    u.created_at,
    u.last_sign_in_at,
    coalesce(b.total_bets, 0) as total_bets,
    coalesce(b.pending_bets, 0) as pending_bets,
    coalesce(b.net_profit_u, 0.0) as net_profit_u
  from auth.users u
  left join public.user_profiles p on p.user_id = u.id
  left join (
    select
      ub.user_id,
      count(*)::bigint as total_bets,
      count(*) filter (where ub.status = 'PENDING')::bigint as pending_bets,
      coalesce(sum(ub.profit_u) filter (where ub.status in ('WON', 'LOST')), 0.0) as net_profit_u
    from public.user_bets ub
    group by ub.user_id
  ) b on b.user_id = u.id
  order by u.created_at desc;
end;
$$;

revoke all on function public.admin_list_users() from public;
grant execute on function public.admin_list_users() to authenticated;
