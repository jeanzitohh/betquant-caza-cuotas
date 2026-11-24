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
