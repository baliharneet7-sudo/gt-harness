export interface Options {
  strict: boolean
}

export function createContainer(options: Options) {
  function isReady(name: string): boolean {
    return name.length > 0 && options.strict
  }
  return {
    resolve(name: string): string {
      return isReady(name) ? name : ""
    },
  }
}
