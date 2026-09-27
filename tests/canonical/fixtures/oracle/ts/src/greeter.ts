export interface Greeter {
  greet(name: string): string
  farewell(name: string): string
}

export class Polite implements Greeter {
  greet(name: string): string {
    return "Hello " + name
  }
  farewell(name: string): string {
    return "Goodbye " + name
  }
}

export class Rude implements Greeter {
  greet(name: string): string {
    return "Yo " + name
  }
}

export function welcome(greeter: Greeter, name: string): string {
  return greeter.greet(name)
}
