import { describe, expect, it } from 'vitest';
import { createApiClient } from '../../src/shared/api/client';

describe('catalog API client', () => {
  it('creates a project with generated request and response types and preserves headers', async () => {
    const requests: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      const request = new Request(input, init);
      requests.push(request);
      return new Response(
        JSON.stringify({
          id: '00000000-0000-4000-8000-000000000001',
          name: 'Synthetic project',
          created_at: '2030-01-01T12:30:00.000000Z',
          deleted_at: null,
        }),
        {
          status: 201,
          headers: {
            'content-type': 'application/json',
            etag: '"project:00000000-0000-4000-8000-000000000001:1"',
            location: '/api/v1/projects/00000000-0000-4000-8000-000000000001',
          },
        },
      );
    };
    const client = createApiClient(fetcher);

    const result = await client.POST('/api/v1/projects', {
      body: { name: 'Synthetic project' },
    });

    expect(result.error).toBeUndefined();
    expect(result.data?.name).toBe('Synthetic project');
    expect(result.response.headers.get('etag')).toBe(
      '"project:00000000-0000-4000-8000-000000000001:1"',
    );
    expect(result.response.headers.get('location')).toBe(
      '/api/v1/projects/00000000-0000-4000-8000-000000000001',
    );
    expect(requests).toHaveLength(1);
    expect(requests[0]?.method).toBe('POST');
    expect(new URL(requests[0]?.url ?? '').pathname).toBe('/api/v1/projects');
    expect(await requests[0]?.json()).toEqual({ name: 'Synthetic project' });
  });

  it('passes typed keyset pagination parameters to the project list', async () => {
    const requests: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      requests.push(new Request(input, init));
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };
    const client = createApiClient(fetcher);

    const result = await client.GET('/api/v1/projects', {
      params: { query: { limit: 25, cursor: 'opaque-cursor' } },
    });

    expect(result.data).toEqual({ items: [], next_cursor: null });
    expect(new URL(requests[0]?.url ?? '').search).toBe(
      '?limit=25&cursor=opaque-cursor',
    );
  });
});
