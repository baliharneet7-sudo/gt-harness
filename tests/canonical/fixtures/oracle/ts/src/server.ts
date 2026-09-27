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

export default app
