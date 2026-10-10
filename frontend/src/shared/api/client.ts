import createClient from 'openapi-fetch';
import type { paths } from './generated/schema';

// The dev proxy exposes the same origin as the browser. Secrets do not enter this client.
export function createApiClient(fetcher: typeof fetch = globalThis.fetch) {
  return createClient<paths>({
    baseUrl: globalThis.location?.origin ?? '',
    fetch: fetcher,
  });
}

export const api = createApiClient();
