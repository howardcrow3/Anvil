import { RpcClient, unwrapResult } from './rpc'

/** The app-wide connection to the agent runtime. */
export const rpc = new RpcClient()

/** Request that throws on the runtime's `{ "error": "…" }` failure results. */
export async function call<T = unknown>(method: string, params: Record<string, unknown> = {}, timeoutMs = 60_000): Promise<T> {
  return unwrapResult<T>(await rpc.request(method, params, timeoutMs))
}
