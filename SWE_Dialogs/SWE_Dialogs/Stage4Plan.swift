import Foundation

struct Stage4Day: Identifiable, Hashable {
    let dayNumber: Int
    let weekNumber: Int
    let prompt: String

    var id: Int { dayNumber }
}

enum Stage4Content {
    static let days: [Stage4Day] = [
        Stage4Day(dayNumber: 1, weekNumber: 1, prompt: "Dialogue between colleagues during fika. Topic: quick life update + how the week is going. Include natural small talk, a few short opinions, and simple reasons/explanations."),
        Stage4Day(dayNumber: 2, weekNumber: 1, prompt: "Dialogue between friends planning something after work. Focus on making suggestions, accepting/declining politely, and agreeing on time/place."),
        Stage4Day(dayNumber: 3, weekNumber: 1, prompt: "Dialogue between colleagues about what happened yesterday and what they learned from it. Include sequencing (first/then/finally) and clarifying (ask to repeat / explain)."),
        Stage4Day(dayNumber: 4, weekNumber: 1, prompt: "Dialogue between coworkers about a TV series or podcast. Include opinions and light disagreement with softening words (maybe/probably/kind of)."),
        Stage4Day(dayNumber: 5, weekNumber: 1, prompt: "Dialogue between neighbors about a small everyday problem (delivery, noise, laundry room, or similar). Focus on explaining the situation, apologizing, and finding a solution."),
        Stage4Day(dayNumber: 6, weekNumber: 1, prompt: "Dialogue between colleagues summarizing the day (keep it general, no work jargon). Include what went well, what was difficult, and what they plan to do tomorrow."),
        Stage4Day(dayNumber: 7, weekNumber: 1, prompt: "Dialogue where one person tells a short personal story and the other reacts and asks follow-up questions. Focus on past tense and natural reactions."),

        Stage4Day(dayNumber: 8, weekNumber: 2, prompt: "Dialogue between colleagues about an update they heard from someone else and what it might mean. Include what is confirmed vs uncertain, and checking details."),
        Stage4Day(dayNumber: 9, weekNumber: 2, prompt: "Dialogue between friends comparing two alternatives (two cafes, gyms, neighborhoods, etc.). Include comparisons, pros/cons, and a final decision."),
        Stage4Day(dayNumber: 10, weekNumber: 2, prompt: "Dialogue about planning the weekend with uncertainty (weather/time/budget). Include natural if... then... thinking."),
        Stage4Day(dayNumber: 11, weekNumber: 2, prompt: "Dialogue in a service situation (clinic, reception, phone support, etc.). Focus on polite questions, clarifying details, and confirming information."),
        Stage4Day(dayNumber: 12, weekNumber: 2, prompt: "Dialogue between friends about a stressful week. Include feelings vocabulary, supportive responses, and simple advice."),
        Stage4Day(dayNumber: 13, weekNumber: 2, prompt: "Dialogue explaining routines/habits (exercise, food, commute, sleep). Include general statements (usually / in general) and small contrasts."),
        Stage4Day(dayNumber: 14, weekNumber: 2, prompt: "Lunch dialogue where they switch topics naturally (work -> weekend -> something they heard -> plans). Include smooth topic transitions."),

        Stage4Day(dayNumber: 15, weekNumber: 3, prompt: "Dialogue reacting to a simple news-type topic (local event, weather warning, transport issue, etc.). Include cautious language (it seems..., I'm not sure...) and short opinions."),
        Stage4Day(dayNumber: 16, weekNumber: 3, prompt: "Dialogue about people/things they know (place, colleague, restaurant, film). Include descriptive who/that/which style connections in a natural way."),
        Stage4Day(dayNumber: 17, weekNumber: 3, prompt: "Dialogue about something being changed/cancelled/delayed (meeting, delivery, reservation). Include everyday phrasing where passive forms might appear (keep it B1-friendly)."),
        Stage4Day(dayNumber: 18, weekNumber: 3, prompt: "Dialogue where one explains a household problem and the other gives step-by-step advice. Include friendly instructions and confirming each step."),
        Stage4Day(dayNumber: 19, weekNumber: 3, prompt: "Dialogue about a decision where the answer is not obvious. Include reasoning, it depends, and giving examples."),
        Stage4Day(dayNumber: 20, weekNumber: 3, prompt: "Dialogue imagining what would you do if.... Keep it realistic and casual (travel, job change, moving, learning, etc.)."),
        Stage4Day(dayNumber: 21, weekNumber: 3, prompt: "Dialogue where one retells a conversation they had earlier and the other asks follow-up questions to understand what was said/decided."),

        Stage4Day(dayNumber: 22, weekNumber: 4, prompt: "Dialogue where they disagree about an everyday topic (remote work, coffee, exercise, city life, etc.) but stay friendly. Include softening and summarizing the other person's point."),
        Stage4Day(dayNumber: 23, weekNumber: 4, prompt: "Dialogue in a customer situation (store, delivery, landlord, service). Focus on explaining the issue clearly, asking what can be done, and agreeing on next steps."),
        Stage4Day(dayNumber: 24, weekNumber: 4, prompt: "Dialogue about inviting someone to a social activity, but one person has constraints (time/energy/budget). Include polite decline, alternative suggestions, and confirming details."),
        Stage4Day(dayNumber: 25, weekNumber: 4, prompt: "Dialogue between colleagues where one summarizes a situation in a structured way (what happened, why it matters, what they'll do next), but still sounds natural."),
        Stage4Day(dayNumber: 26, weekNumber: 4, prompt: "Dialogue where a misunderstanding happens and they fix it by asking clarifying questions and rephrasing. Keep it realistic."),
        Stage4Day(dayNumber: 27, weekNumber: 4, prompt: "Casual friend dialogue with more spoken Swedish feel (some common filler words and short interjections), but still clear at B1 level."),
        Stage4Day(dayNumber: 28, weekNumber: 4, prompt: "Dialogue that mixes: a short past story, an opinion about it, and a plan for next week. Include natural transitions and a confident B1 flow.")
    ]
}
