export const meta = {
  name: 'season-1-awards-vote',
  description: 'Season 1 regular-season awards: 30 writers, 15 coaching staffs and two panels cast independent secret ballots',
  phases: [
    { title: 'Writers', detail: '30 BBWAA-style writers, two per city: MVP, Cy Young, Rookie, Manager, Relief Pitcher, Comeback, DH' },
    { title: 'Coaches', detail: '15 coaching staffs: Silver Sluggers and Gold Gloves' },
    { title: 'Panels', detail: 'Hall of Fame hitters panel and retired relievers panel' },
  ],
}

const DOSSIER = '/Users/Nic/projects/show-h2h/awards/season-N/dossier.md'

const CITIES = ['Birds', 'Worms', 'New York', 'Los Angeles', 'Chicago', 'Philadelphia', 'Atlanta', 'St. Louis',
  'San Francisco', 'San Diego', 'Cincinnati', 'Pittsburgh', 'Miami', 'Denver', 'Phoenix']

const LENSES = [
  'a traditionalist: batting average, home runs, RBI, wins and ERA carry the most weight with you',
  'a sabermetric voter: you care about OBP, slugging, rate stats relative to the league line, WHIP and strikeout-to-walk ratio, and you distrust RBI and pitcher wins',
  'a "value means winning" voter: you believe the most valuable players are the ones who drove a winning club',
  'a volume voter: durability and bulk matter to you; you are sceptical of small samples and reward the players who carried the largest workloads',
  'a two-way voter: you weigh defence and baserunning heavily alongside the bat',
  'a narrative voter: you care about clutch moments, go-ahead hits and how the season actually unfolded',
  'a contrarian who actively looks for the deserving candidate on the losing club and resists the obvious pick unless the numbers force it',
  'a pitching-first voter: you think dominant starting pitching is the most valuable thing in the sport and are willing to put a pitcher at the top of an MVP ballot',
  'a peak-performance voter: you reward the single most dominant level of play, even over somewhat fewer chances',
  'a balanced veteran voter with no strong hobby-horse who weighs everything evenly',
]

const PICK = { type: 'object', properties: { player: { type: 'string' }, club: { type: 'string', enum: ['Birds', 'Worms'] } }, required: ['player', 'club'] }
const list = (n) => ({ type: 'array', items: PICK, minItems: n, maxItems: n })

const COMMON = `Read the awards dossier at ${DOSSIER} with the Read tool. It is the ONLY source you may use: do not search the web, do not open any other file, and do not rely on what you know about the real-life players — these are video-game cards and only what happened in this league's 29-game regular season counts. The same surname can exist on both clubs as two different cards, so always give the club. Copy player names exactly as the dossier spells them. Vote independently and decisively; this is a secret ballot and nobody will see it but the teller.`

const WRITER_SCHEMA = (relief) => ({
  type: 'object',
  properties: Object.assign({
    mvp: list(10),
    cy_young: list(5),
    rookie: list(3),
    manager: { type: 'array', items: { type: 'string', enum: ['LinguiniEater', 'TallThibaut48'] }, minItems: 2, maxItems: 2 },
    comeback: PICK,
    dh: PICK,
    note: { type: 'string' },
  }, relief ? { relief_pitcher: list(3) } : {}),
  required: ['mvp', 'cy_young', 'rookie', 'manager', 'comeback', 'dh', 'note'].concat(relief ? ['relief_pitcher'] : []),
})

function writerPrompt(city, seat, lens, relief) {
  const beat = city === 'Birds' || city === 'Worms'
    ? `You cover the ${city} every day as a beat writer. You know that club best, but you are a professional and vote on merit.`
    : `You are an out-of-town writer from the ${city} chapter with no tie to either club.`
  return `You are a member of the Baseball Writers' Association (seat ${seat} of 2 for the ${city} chapter) casting your end-of-season awards ballot. ${beat} As a voter you are ${lens}.

${COMMON}

Fill in every award, ranked best first:
- mvp: 10 different players, any position, pitchers eligible. (Scored 14-9-8-7-6-5-4-3-2-1.)
- cy_young: 5 different pitchers, starters or relievers. (7-4-3-2-1.)
- rookie: 3 different players marked ROOKIE in the dossier, hitters or pitchers. (5-3-1.)
- manager: both managers, first choice first. (5-3.) Judge the job done against expectations, not just the record.
- comeback: one player who returned to a high level after struggling before the league opened — use the "before vs Season 1" tables.
- dh: the outstanding designated hitter — one player who played primarily DH.${relief ? `
- relief_pitcher: 3 different pitchers who worked primarily in relief ("relief G" in the dossier), best first. (5-3-1.)` : ''}
- note: two sentences on why your first-place MVP and first-place Cy Young votes went where they did.`
}

const SS_POS = ['C', '1B', '2B', '3B', 'SS', 'OF1', 'OF2', 'OF3', 'DH', 'UTIL']
const GG_POS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'UTIL']
const posObj = (keys) => ({ type: 'object', properties: Object.fromEntries(keys.map((k) => [k, PICK])), required: keys })
const COACH_SCHEMA = {
  type: 'object',
  properties: { silver_slugger: posObj(SS_POS), gold_glove: posObj(GG_POS), best_defenders: list(3), note: { type: 'string' } },
  required: ['silver_slugger', 'gold_glove', 'best_defenders', 'note'],
}

function coachPrompt(city, lens) {
  const own = city === 'Birds' || city === 'Worms'
  return `You are the manager and coaching staff of the ${city} club, filling in the staff's single ballot for the Silver Slugger and Gold Glove awards. ${own
    ? `LEAGUE RULE: a staff may NOT vote for players on its own club. Every pick on this ballot must be a player from the other club (${city === 'Birds' ? 'Worms' : 'Birds'}).`
    : 'Your club is not one of the two in this league, so you may vote for anyone on either club.'} As evaluators you are ${lens}.

${COMMON}

- silver_slugger: the best OFFENSIVE player at each position, judged on the bat only. A player is eligible at the position he played most ("pos (games)" in the hitters table). OF1, OF2, OF3 are three different outfielders regardless of which outfield spot. UTIL is the best hitter who played two or more different positions.
- gold_glove: the best DEFENSIVE player at each position, judged on the glove only — use the fielding table, weighing both how many outs a fielder converted for the games he played and how few errors he made. P is a pitcher. Catchers leave almost no trace in the data; pick on games caught and errors. UTIL is the best defender who played two or more positions. A player wins at the position he played most.
- best_defenders: the three best overall defenders in the league at any position, best first (this decides the Platinum Glove).
- note: one sentence on your hardest call.`
}

const HOF_SCHEMA = {
  type: 'object',
  properties: {
    hank_aaron: list(3),
    all_mlb_first: posObj(['C', '1B', '2B', '3B', 'SS', 'OF1', 'OF2', 'OF3', 'DH', 'SP1', 'SP2', 'SP3', 'SP4', 'SP5', 'RP1', 'RP2']),
    all_mlb_second: posObj(['C', '1B', '2B', '3B', 'SS', 'OF1', 'OF2', 'OF3', 'DH', 'SP1', 'SP2', 'SP3', 'SP4', 'SP5', 'RP1', 'RP2']),
    note: { type: 'string' },
  },
  required: ['hank_aaron', 'all_mlb_first', 'all_mlb_second', 'note'],
}
const HOF = ['a slugger who thinks power is the whole point of hitting', 'a contact hitter who prizes batting average and putting the ball in play',
  'an on-base machine who values not making outs above everything', 'a five-tool outfielder who counts baserunning as offence',
  'a catcher who studies how hitters were actually pitched and values consistency over a hot streak']
function hofPrompt(i) {
  return `You are a Hall of Fame player (${HOF[i]}) sitting on the league's five-member expert panel.

${COMMON}

- hank_aaron: the three best OVERALL OFFENSIVE performers of the regular season, best first, regardless of position or club. Hitting and baserunning only. (5-3-1.)
- all_mlb_first and all_mlb_second: the league's First Team and Second Team. One player per slot and nobody on both teams: catcher, 1B, 2B, 3B, SS, three outfielders, a DH, five starting pitchers and two relief pitchers on each. Position players go at the position they played most; overall play counts (bat, legs and glove). With so few regulars at some positions the Second Team will include thin résumés — pick the best available rather than leaving a slot weak on purpose.
- note: one sentence on your Hank Aaron pick.`
}

const REL_SCHEMA = { type: 'object', properties: { reliever: list(3), note: { type: 'string' } }, required: ['reliever', 'note'] }
const REL = ['a ninth-inning closer who believes the save is the hardest out in baseball', 'a multi-inning fireman from the 1970s who values innings and leverage over the save statistic',
  'a strikeout closer who judges a reliever by how unhittable he was', 'a setup man who thinks holds and clean middle innings are badly underrated',
  'a control artist who judges relievers by baserunners allowed']
function relPrompt(i) {
  return `You are a retired Hall of Fame-calibre relief pitcher (${REL[i]}) on the five-member panel that picks the Reliever of the Year.

${COMMON}

- reliever: the three best relief pitchers of the regular season, best first. (5-3-1.) Only pitchers who worked primarily in relief are eligible ("relief G" in the dossier). Samples are tiny, so weigh workload and role alongside the rate stats.
- note: one sentence on your first-place vote.`
}

const jobs = []
CITIES.forEach((city, c) => {
  for (let seat = 1; seat <= 2; seat++) {
    const lens = LENSES[(c * 3 + (seat - 1) * 7) % LENSES.length]
    const relief = seat === 1
    jobs.push(() => agent(writerPrompt(city, seat, lens, relief), { label: `writer:${city}#${seat}`, phase: 'Writers', schema: WRITER_SCHEMA(relief), effort: 'medium' })
      .then((b) => b && { body: 'writer', city, seat, lens, ballot: b }))
  }
})
CITIES.forEach((city, c) => {
  const lens = LENSES[(c * 7 + 4) % LENSES.length]
  jobs.push(() => agent(coachPrompt(city, lens), { label: `staff:${city}`, phase: 'Coaches', schema: COACH_SCHEMA, effort: 'medium' })
    .then((b) => b && { body: 'staff', city, lens, ballot: b }))
})
for (let i = 0; i < 5; i++) {
  jobs.push(() => agent(hofPrompt(i), { label: `hof:${i + 1}`, phase: 'Panels', schema: HOF_SCHEMA, effort: 'medium' })
    .then((b) => b && { body: 'hof', seat: i + 1, lens: HOF[i], ballot: b }))
  jobs.push(() => agent(relPrompt(i), { label: `reliever-panel:${i + 1}`, phase: 'Panels', schema: REL_SCHEMA, effort: 'medium' })
    .then((b) => b && { body: 'relievers', seat: i + 1, lens: REL[i], ballot: b }))
}

const results = await parallel(jobs)
const ballots = results.filter(Boolean)
log(`${ballots.length} of ${jobs.length} ballots returned`)
return { expected: jobs.length, returned: ballots.length, ballots }
