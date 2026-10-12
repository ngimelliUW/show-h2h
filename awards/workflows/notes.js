export const meta = {
  name: 'season-1-awards-notes',
  description: 'Each of the 55 voters signs their already-cast ballot and writes a personal note explaining every vote',
  phases: [{ title: 'Notes', detail: 'one voter per agent, annotating the ballot they already cast' }],
}

const DOSSIER = '/Users/Nic/projects/show-h2h/awards/season-N/dossier.md'
const CAST = '/Users/Nic/projects/show-h2h/awards/season-N/cast'
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
const HOF = ['a slugger who thinks power is the whole point of hitting', 'a contact hitter who prizes batting average and putting the ball in play',
  'an on-base machine who values not making outs above everything', 'a five-tool outfielder who counts baserunning as offence',
  'a catcher who studies how hitters were actually pitched and values consistency over a hot streak']
const REL = ['a ninth-inning closer who believes the save is the hardest out in baseball', 'a multi-inning fireman from the 1970s who values innings and leverage over the save statistic',
  'a strikeout closer who judges a reliever by how unhittable he was', 'a setup man who thinks holds and clean middle innings are badly underrated',
  'a control artist who judges relievers by baserunners allowed']
// Rebuilt in exactly the order the ballots were cast, so index i is file cast/i.json.
const ballots = []
CITIES.forEach((city, c) => { for (let seat = 1; seat <= 2; seat++) ballots.push({ body: 'writer', city, seat, lens: LENSES[(c * 3 + (seat - 1) * 7) % LENSES.length], relief: seat === 1 }) })
CITIES.forEach((city, c) => ballots.push({ body: 'staff', city, seat: 0, lens: LENSES[(c * 7 + 4) % LENSES.length] }))
for (let i = 0; i < 5; i++) { ballots.push({ body: 'hof', seat: i + 1, lens: HOF[i] }); ballots.push({ body: 'relievers', seat: i + 1, lens: REL[i] }) }

const str = { type: 'string' }
const obj = (keys) => ({ type: 'object', properties: Object.fromEntries(keys.map((k) => [k, str])), required: keys })
const KEYS = {
  writer: (b) => ['mvp', 'mvp_down_ballot', 'cy_young', 'rookie', 'manager', 'comeback', 'dh'].concat(b.relief ? ['relief_pitcher'] : []),
  staff: () => ['silver_slugger', 'gold_glove', 'best_defenders', 'hardest_call'],
  hof: () => ['hank_aaron', 'all_league_teams'],
  relievers: () => ['reliever'],
}
const WHO = {
  writer: (b) => `a baseball writer in the ${b.city} chapter (seat ${b.seat}). ${b.city === 'Birds' || b.city === 'Worms' ? `You cover the ${b.city} every day.` : 'You are an out-of-town voter with no tie to either club.'}`,
  staff: (b) => `the manager of the ${b.city} club, signing on behalf of your coaching staff.${b.city === 'Birds' || b.city === 'Worms' ? ' League rules barred your staff from voting for your own players.' : ''}`,
  hof: () => 'a Hall of Fame player on the five-member expert panel.',
  relievers: () => 'a retired relief pitcher on the five-member Reliever of the Year panel.',
}
const GUIDE = {
  writer: `- mvp: why your first-place vote went where it did, and who you agonised over leaving second.
- mvp_down_ballot: one or two sentences on the rest of your ten — a name you were glad to squeeze on, or one you could not find room for.
- cy_young, rookie, manager, comeback, dh (and relief_pitcher if it is on your ballot): two or three sentences each on that vote.`,
  staff: `- silver_slugger: two or three sentences on the bats you picked — the easiest call and the closest one.
- gold_glove: two or three sentences on the gloves, including how you handled positions where the data was thin.
- best_defenders: why you ranked your top three defenders that way.
- hardest_call: the one pick your staff argued about longest.`,
  hof: `- hank_aaron: two or three sentences on your ranking of the three best offensive players.
- all_league_teams: two or three sentences on your First and Second Teams — the toughest slot to fill and any pick you expect to be argued with.`,
  relievers: `- reliever: three or four sentences on your ranking, from one reliever to another.`,
}

const results = await parallel(ballots.map((b, i) => () => {
  const keys = KEYS[b.body](b)
  const schema = {
    type: 'object',
    properties: { byline: str, outlet: str, notes: obj(keys) },
    required: ['byline', 'outlet', 'notes'],
  }
  const prompt = `You are ${WHO[b.body](b)} As a voter you are ${b.lens}.

You have ALREADY cast the secret ballot below for the Season 1 regular-season awards of a two-club league (Birds and Worms). The ballot is final — do not change, reorder or second-guess any pick. Your job now is to sign it and write a personal note explaining each vote, for the league's public record.

YOUR BALLOT is the JSON file ${CAST}/${String(i).padStart(2, '0')}.json — read it first with the Read tool (lists are ranked best first).

Then read the awards dossier at ${DOSSIER} with the Read tool so every number you cite is real. It is the only source you may use; every statistic in a note must come from it. These are video-game cards, so do not bring in anything about the real-life players.

Write:
- byline: an invented name for yourself. It must be fictional — never the name of a real writer, manager, coach or player.
- outlet: an invented ${b.body === 'writer' ? 'newspaper or outlet' : b.body === 'staff' ? 'job title and club, e.g. "Manager, ' + b.city + '"' : 'one-line description of who you were as a player (no real names)'}.
- notes, written in the first person, in your own voice, with the personality your voting philosophy implies. Be specific, opinionated and a little fun — a grumble, a joke, a line you would actually put in a column — but keep every claim true to the dossier and to the ballot above:
${GUIDE[b.body]}`
  const label = `${b.body}:${b.city || b.seat}${b.body === 'writer' ? '#' + b.seat : ''}`
  return agent(prompt, { label, phase: 'Notes', schema, effort: 'low' }).then((r) => r && Object.assign({ index: i }, r))
}))
const notes = results.filter(Boolean)
log(`${notes.length} of ${ballots.length} voters signed their ballots`)
return { expected: ballots.length, returned: notes.length, notes }
