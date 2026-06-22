declare module 'pg' {
  export interface QueryResultRow {
    [column: string]: unknown
  }

  export interface QueryResult<R extends QueryResultRow = QueryResultRow> {
    rows: R[]
  }

  export interface ClientConfig {
    host?: string
    port?: number
    user?: string
    password?: string
    database?: string
  }

  export class Client {
    constructor(config?: ClientConfig)
    connect(): Promise<void>
    query<R extends QueryResultRow = QueryResultRow>(text: string, values?: unknown[]): Promise<QueryResult<R>>
    end(): Promise<void>
  }
}
