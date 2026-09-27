const Router = require("koa-router")

const router = new Router()

router.get("/messages", (ctx) => {
  ctx.body = []
})

module.exports = router
