import Foundation

enum DialogLevel: String, CaseIterable, Identifiable {
    case b1 = "B1"
    case b2 = "B2"

    var id: String { rawValue }
}

struct DialogDay: Identifiable, Hashable {
    let level: DialogLevel
    let stageNumber: Int
    let dayNumber: Int
    let weekNumber: Int
    let prompt: String

    var id: String {
        "\(level.rawValue)-\(stageNumber)-\(weekNumber)-\(dayNumber)"
    }

    var copyHeader: String {
        "\(level.rawValue), Stage \(stageNumber), Week \(weekNumber), Day \(dayNumber)"
    }

    var progressIndex: Int {
        ((weekNumber - 1) * 7) + dayNumber
    }

    var copyText: String {
        "\(copyHeader)\n\n\(prompt)"
    }
}

enum DialogContent {
    static func days(for level: DialogLevel, stage: Int) -> [DialogDay] {
        switch (level, stage) {
        case (.b1, 1):
            return b1Stage1
        case (.b1, 2):
            return b1Stage2
        case (.b1, 3):
            return b1Stage3
        case (.b1, 4):
            return b1Stage4
        default:
            return []
        }
    }

    private static func makeDays(level: DialogLevel, stage: Int, weekPrompts: [[String]]) -> [DialogDay] {
        weekPrompts.enumerated().flatMap { weekIndex, prompts in
            prompts.enumerated().map { dayIndex, prompt in
                DialogDay(
                    level: level,
                    stageNumber: stage,
                    dayNumber: dayIndex + 1,
                    weekNumber: weekIndex + 1,
                    prompt: prompt
                )
            }
        }
    }

    private static let b1Stage1 = makeDays(
        level: .b1,
        stage: 1,
        weekPrompts: [
            [
                #"Write a short Swedish dialogue (4–6 lines) between two people greeting each other in the morning. Use simple present tense and greetings."#,
                #"Create a dialogue between two people talking about their daily routine. Use the present tense and time phrases like ‘på morgonen’ and ‘efter jobbet’."#,
                #"Make a dialogue where someone describes their morning to a colleague. Include simple actions like waking up, eating breakfast, and going to work."#,
                #"Write a dialogue in Swedish where one person asks how someone’s day is going and they respond. Use simple adjectives like ‘bra’, ‘trött’, ‘glad’."#,
                #"Create a dialogue between two coworkers meeting at a fika break. One offers coffee and they talk briefly."#,
                #"Write a short Swedish dialogue where one person asks questions about someone’s job and daily tasks."#,
                #"Create a short role-play where someone introduces themselves and mentions where they live and work."#
            ],
            [
                #"Write a Swedish dialogue where someone talks about what they did yesterday. Use regular preterite verbs like ‘jobbade’, ‘lagade’, ‘tittade’."#,
                #"Create a short Swedish dialogue where someone describes their weekend using simple past verbs."#,
                #"Write a Swedish dialogue between two people where one tells a short story about last Saturday. Include sequencing words like ‘först’, ‘sedan’, ‘till slut’."#,
                #"Create a dialogue in Swedish where one person says what they had for dinner last night and describes if it was good or not."#,
                #"Write a Swedish dialogue about someone describing their Sunday. Include common weekend activities."#,
                #"Create a Swedish conversation about a trip someone took recently. Keep it simple and in past tense."#,
                #"Write a Swedish dialogue where someone is asked what they did this morning. Use common time phrases."#
            ],
            [
                #"Create a dialogue in Swedish where someone talks about what they must do today (use ‘måste’)."#,
                #"Write a Swedish conversation where someone says what they can and can’t do today (use ‘kan’ and negation)."#,
                #"Create a dialogue where someone says what they want to do tonight and what they don’t want to do (use ‘vill’ and negation)."#,
                #"Write a short dialogue where someone describes their typical day using modals like ‘brukar’, ‘kan’, and present tense."#,
                #"Create a dialogue in Swedish where two people discuss what they are going to do tomorrow. Use ‘ska’ + infinitive."#,
                #"Write a Swedish conversation about evening routines and include negation (e.g. 'I don’t watch TV' – 'Jag tittar inte på tv')."#,
                #"Create a dialogue where someone gives short reasons for why they can’t or won’t do something."#
            ],
            [
                #"Write a dialogue in Swedish where someone describes their apartment or home. Use adjectives."#,
                #"Create a Swedish dialogue where someone describes their family members (e.g. names, traits, jobs)."#,
                #"Write a dialogue in Swedish where one person describes their neighborhood and daily commute."#,
                #"Create a dialogue where two people talk about their plans for the weekend using future tense and adjectives."#,
                #"Write a short dialogue about someone’s morning using sequencing words like ‘först’, ‘sedan’, ‘till slut’."#,
                #"Create a Swedish dialogue where someone says how they feel today and why. Include emotional adjectives and reasons."#,
                #"Write a Swedish dialogue that includes greetings, a description of the weekend, and future plans."#
            ]
        ]
    )

    private static let b1Stage2 = makeDays(
        level: .b1,
        stage: 2,
        weekPrompts: [
            [
                #"Dialogue on favourite leisure activities, practising subordinate clauses expressing reasons with för att and basic att clauses."#,
                #"Dialogue on daily routines, highlighting för att purpose clauses and simple att clauses."#,
                #"Dialogue about feelings (tired, happy, stressed) and what actions help, using both att and för att constructions."#,
                #"Dialogue on today’s weather and how it affects plans, focusing on för att purpose clauses and one comparative adjective."#,
                #"Dialogue planning the weekend, using vill att… wishes plus för att reasons, with a couple of irregular past-tense verbs."#,
                #"Dialogue comparing weekdays (for example Monday vs Friday) with comparative adjectives and some att clauses for opinions."#,
                #"Review dialogue about the weekend that mixes irregular past verbs with att and för att clauses."#
            ],
            [
                #"Dialogue comparing yesterday’s and today’s weather, practising när clauses and comparatives."#,
                #"Dialogue recounting last weekend’s events, using irregular past verbs and när jag… clauses."#,
                #"Dialogue deciding what to do if the weather changes, introducing first-conditional structures with om + future."#,
                #"Dialogue contrasting om (if) and när (when) in everyday situations."#,
                #"Dialogue about childhood hobbies using när jag var liten plus irregular past verbs and one comparative."#,
                #"Dialogue planning a short trip, integrating om + future (ska / kommer att) and a comparative."#,
                #"Review dialogue mixing att, för att, när, om, irregular past forms and comparatives."#
            ],
            [
                #"Dialogue suggesting weekend activities, using future forms (ska, kommer att) and question format Ska vi …?"#,
                #"Dialogue about a picnic that uses first-conditional sentences (om + future) for weather-dependent plans."#,
                #"Dialogue comparing the seasons, employing several comparatives and at least one superlative, plus a future plan."#,
                #"Dialogue arranging a concert visit, practising tror att … + future forms."#,
                #"Dialogue about a dream holiday combining irregular past memories with future conditional plans."#,
                #"Dialogue giving opinions on hobbies (tycker att …) alongside future intentions and comparatives."#,
                #"Review dialogue integrating all Week 3 elements: future forms, first conditional and comparatives."#
            ],
            [
                #"Dialogue comparing two Swedish cities, heavy on comparatives and superlatives."#,
                #"Dialogue sharing opinions on a TV series, mixing tycker att …, comparatives/superlatives and one för att reason."#,
                #"Dialogue choosing a holiday destination using first conditional plus comparisons (If Spain is warmer, it’s the best choice)."#,
                #"Dialogue describing emotional reactions to news, practising för att clauses for reasons."#,
                #"Narrative dialogue recounting a team-building event, with irregular past verbs, när clauses and a comparative."#,
                #"Dialogue predicting next year, using kommer att, one om condition, tror att … and comparatives."#,
                #"Grand review dialogue naturally blending all Stage 2 grammar: att, för att, när, om, irregular past, future forms, first conditional, comparatives and a superlative."#
            ]
        ]
    )

    private static let b1Stage3 = makeDays(
        level: .b1,
        stage: 3,
        weekPrompts: [
            [
                #"Weekend debrief with added detail — connected past narration (preterite + present perfect), sequencing words, and relative clauses with som."#,
                #"Planning a home task — present/future plans (ska/kommer att), indirect questions (vet du om…?), and det beror på."#,
                #"Explaining a simple process — step-by-step instructions, imperatives softened with modals (vi kan / du kan), purpose with så att."#,
                #"TV show review — opinions (tycker att/tror att), simple comparisons, and som-clauses to specify characters or episodes."#,
                #"Moving/ furniture talk — adjectives & agreement in context, useful collocations (IKEA routines), som to define items."#,
                #"Minor mishap story — past narration plus contrast with men, fastän, även om; reactions (Vad synd!, Vilken tur!)."#,
                #"Trip choice A vs B — trade-off language (fördelar/nackdelar), comparisons, and det beror på."#
            ],
            [
                #"Retelling what a friend said — reported speech with sa att, future in the past (skulle komma), reported questions (frågade om)."#,
                #"Workplace small talk/rumors — hedging (kanske, nog, väl), polite distance, reported speech."#,
                #"Simple news recap — Har du hört att…? summaries; connectors (därför, ändå, men); neutral reactions."#,
                #"New rule/policy at the gym — indirect questions (vet du hur/när/om), clarifications, polite requests."#,
                #"Missed fika—what happened? — apologies + someone recounts events with sequencing and reported speech."#,
                #"Making plans with constraints — modals (kan, måste, borde, får) + conditional result (om… så…)."#,
                #"Giving and responding to advice — imperatives + softeners (skulle kunna, kanske), gentle disagreement."#
            ],
            [
                #"Weather-dependent plan — real conditionals (om… så), ska vs kommer att, time adverbs."#,
                #"If I had more time/money… — hypothetical with om jag hade… skulle jag… (optionally recognise vore)."#,
                #"Troubleshooting at home — conditional suggestions (skulle det funka om…?), fallback options (annars)."#,
                #"Choosing between two offers — pros/cons; concession with trots att/även om; concluding choice."#,
                #"Polite requests — Skulle du kunna…? and Vore det okej om…?; gratitude/decline formulas."#,
                #"Speculating about someone’s plan — inference language (det verkar som att…, de kanske tänker…), cautious opinions."#,
                #"Goals & consequences — “what would happen if…” chains; linking words (därför att, därför, då)."#
            ],
            [
                #"Delivery/repair updates — recognize and use everyday passives (paketet levererades, datorn fixas), plus active ↔ passive rephrasing."#,
                #"Instruction-style talk — -s passive in instructions (dörren öppnas), past participles as adjectives (lampan är lagad/trasig)."#,
                #"Cancellations & changes — event logistics: Mötet ställs in, tiden blev ändrad; polite reactions & next steps."#,
                #"News bite + reactions — short current-events summary using common passives (det sägs att…, en person greps) and neutral adjectives."#,
                #"Explaining a Swedish tradition — process description with sequencing words; occasional passive (sill serveras), comparisons with your own habits."#,
                #"Light “mini-debate” — everyday topic (environment/health/tech): softening disagreement, å ena sidan … å andra sidan, polite closing."#,
                #"Wrap-up conversation — mixed review: relative clauses, reported speech, real + hypothetical conditionals, and passive recognition in one natural dialogue."#
            ]
        ]
    )

    private static let b1Stage4 = makeDays(
        level: .b1,
        stage: 4,
        weekPrompts: [
            [
                #"Dialogue between colleagues during fika. Topic: quick life update + how the week is going. Include natural small talk, a few short opinions, and simple reasons/explanations."#,
                #"Dialogue between friends planning something after work. Focus on making suggestions, accepting/declining politely, and agreeing on time/place."#,
                #"Dialogue between colleagues about what happened yesterday and what they learned from it. Include sequencing (first/then/finally) and clarifying (ask to repeat / explain)."#,
                #"Dialogue between coworkers about a TV series or podcast. Include opinions and light disagreement with softening words (maybe/probably/kind of)."#,
                #"Dialogue between neighbors about a small everyday problem (delivery, noise, laundry room, or similar). Focus on explaining the situation, apologizing, and finding a solution."#,
                #"Dialogue between colleagues summarizing the day (keep it general, no work jargon). Include what went well, what was difficult, and what they plan to do tomorrow."#,
                #"Dialogue where one person tells a short personal story and the other reacts and asks follow-up questions. Focus on past tense and natural reactions."#
            ],
            [
                #"Dialogue between colleagues about an update they heard from someone else and what it might mean. Include what is confirmed vs uncertain, and checking details."#,
                #"Dialogue between friends comparing two alternatives (two cafes, gyms, neighborhoods, etc.). Include comparisons, pros/cons, and a final decision."#,
                #"Dialogue about planning the weekend with uncertainty (weather/time/budget). Include natural if... then... thinking."#,
                #"Dialogue in a service situation (clinic, reception, phone support, etc.). Focus on polite questions, clarifying details, and confirming information."#,
                #"Dialogue between friends about a stressful week. Include feelings vocabulary, supportive responses, and simple advice."#,
                #"Dialogue explaining routines/habits (exercise, food, commute, sleep). Include general statements (usually / in general) and small contrasts."#,
                #"Lunch dialogue where they switch topics naturally (work -> weekend -> something they heard -> plans). Include smooth topic transitions."#
            ],
            [
                #"Dialogue reacting to a simple news-type topic (local event, weather warning, transport issue, etc.). Include cautious language (it seems..., I'm not sure...) and short opinions."#,
                #"Dialogue about people/things they know (place, colleague, restaurant, film). Include descriptive who/that/which style connections in a natural way."#,
                #"Dialogue about something being changed/cancelled/delayed (meeting, delivery, reservation). Include everyday phrasing where passive forms might appear (keep it B1-friendly)."#,
                #"Dialogue where one explains a household problem and the other gives step-by-step advice. Include friendly instructions and confirming each step."#,
                #"Dialogue about a decision where the answer is not obvious. Include reasoning, it depends, and giving examples."#,
                #"Dialogue imagining what would you do if.... Keep it realistic and casual (travel, job change, moving, learning, etc.)."#,
                #"Dialogue where one retells a conversation they had earlier and the other asks follow-up questions to understand what was said/decided."#
            ],
            [
                #"Dialogue where they disagree about an everyday topic (remote work, coffee, exercise, city life, etc.) but stay friendly. Include softening and summarizing the other person's point."#,
                #"Dialogue in a customer situation (store, delivery, landlord, service). Focus on explaining the issue clearly, asking what can be done, and agreeing on next steps."#,
                #"Dialogue about inviting someone to a social activity, but one person has constraints (time/energy/budget). Include polite decline, alternative suggestions, and confirming details."#,
                #"Dialogue between colleagues where one summarizes a situation in a structured way (what happened, why it matters, what they'll do next), but still sounds natural."#,
                #"Dialogue where a misunderstanding happens and they fix it by asking clarifying questions and rephrasing. Keep it realistic."#,
                #"Casual friend dialogue with more spoken Swedish feel (some common filler words and short interjections), but still clear at B1 level."#,
                #"Dialogue that mixes: a short past story, an opinion about it, and a plan for next week. Include natural transitions and a confident B1 flow."#
            ]
        ]
    )
}

typealias Stage4Day = DialogDay
typealias Stage4Content = DialogContent
