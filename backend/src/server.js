import "dotenv/config";
import express from "express";
import OpenAI from "openai";

const port = Number(process.env.PORT || 3001);
const model = process.env.OPENAI_CHAT_MODEL || "gpt-5.4-nano";
const apiKey = process.env.OPENAI_API_KEY;

if (!apiKey) {
  console.error("Missing OPENAI_API_KEY. Add it to backend/.env");
  process.exit(1);
}

const openai = new OpenAI({ apiKey });
const app = express();

app.use(express.json({ limit: "1mb" }));

app.get("/health", (_req, res) => {
  res.json({ ok: true, model });
});

app.post("/chat/new", async (_req, res) => {
  try {
    const conversation = await openai.conversations.create();
    res.status(201).json({ conversationId: conversation.id, model });
  } catch (error) {
    console.error("Failed to create conversation", error);
    res.status(500).json({ error: "Failed to create conversation" });
  }
});

app.post("/chat/:conversationId/message", async (req, res) => {
  const conversationId = req.params.conversationId;
  const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";

  if (!conversationId) {
    return res.status(400).json({ error: "Missing conversationId" });
  }

  if (!message) {
    return res.status(400).json({ error: "Message must be a non-empty string" });
  }

  try {
    const response = await openai.responses.create({
      model,
      conversation: conversationId,
      input: [{ role: "user", content: message }]
    });

    res.json({
      conversationId,
      responseId: response.id,
      outputText: response.output_text
    });
  } catch (error) {
    console.error("Failed to send message", error);
    res.status(500).json({ error: "Failed to send message" });
  }
});

app.listen(port, () => {
  console.log(`Chat backend listening on http://localhost:${port}`);
  console.log(`Model: ${model}`);
});
