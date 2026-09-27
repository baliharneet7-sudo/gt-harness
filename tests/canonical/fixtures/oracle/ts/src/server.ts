import express from "express"

const app = express()

function audit(req: any, res: any, next: any) {
  next()
}

function loadItems(): string[] {
  return ["a", "b"]
}

function listItems(req: any, res: any) {
  res.json(loadItems())
}

app.use(audit)
app.get("/api/items", listItems)
app.get("/api/health", (req: any, res: any) => res.json({ ok: true }))

export default app
