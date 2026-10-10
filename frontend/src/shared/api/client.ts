import createClient from 'openapi-fetch';
import type { paths } from './generated/schema';

// The dev proxy exposes the same origin as the browser. Secrets do not enter this client.
export const api = createClient<paths>({ baseUrl: '' });
