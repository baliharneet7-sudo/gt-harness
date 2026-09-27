import { createContainer } from "../container"

describe("container", () => {
  it("resolves a ready name", () => {
    const container = createContainer({ strict: true })
    expect(container.resolve("db")).toBe("db")
  })
})
