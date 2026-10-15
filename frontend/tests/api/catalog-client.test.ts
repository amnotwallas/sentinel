import { describe, expect, it } from 'vitest';
import { createApiClient } from '../../src/shared/api/client';
import type { components } from '../../src/shared/api/generated/schema';

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

  it('reads a project with its generated response type and exposes its ETag', async () => {
    const projectId = '00000000-0000-4000-8000-000000000001';
    const fetcher: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          id: projectId,
          name: 'Synthetic project',
          created_at: '2030-01-01T12:30:00.000000Z',
          deleted_at: null,
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json',
            etag: '"project:00000000-0000-4000-8000-000000000001:1"',
          },
        },
      );
    const client = createApiClient(fetcher);

    const result = await client.GET('/api/v1/projects/{project_id}', {
      params: { path: { project_id: projectId } },
    });

    expect(result.data?.name).toBe('Synthetic project');
    expect(result.response.headers.get('etag')).toBe(
      '"project:00000000-0000-4000-8000-000000000001:1"',
    );
  });

  it('reads a paginated environment page with generated item types', async () => {
    const projectId = '00000000-0000-4000-8000-000000000001';
    const environmentId = '00000000-0000-4000-8000-000000000010';
    const requests: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      requests.push(new Request(input, init));
      return new Response(
        JSON.stringify({
          items: [
            {
              id: environmentId,
              project_id: projectId,
              name: 'Production',
              active_revision_id: '00000000-0000-4000-8000-000000000013',
              active_revision_version: 1,
              created_at: '2030-01-01T12:30:00.000000Z',
            },
          ],
          next_cursor: 'next-environment-cursor',
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    };
    const client = createApiClient(fetcher);

    const result = await client.GET(
      '/api/v1/projects/{project_id}/environments',
      {
        params: {
          path: { project_id: projectId },
          query: { limit: 25, cursor: 'opaque-cursor' },
        },
      },
    );

    expect(result.data?.items[0]?.name).toBe('Production');
    expect(result.data?.next_cursor).toBe('next-environment-cursor');
    expect(new URL(requests[0]?.url ?? '').pathname).toBe(
      `/api/v1/projects/${projectId}/environments`,
    );
    expect(new URL(requests[0]?.url ?? '').search).toBe(
      '?limit=25&cursor=opaque-cursor',
    );
  });

  it('updates an environment with generated document and If-Match types', async () => {
    const requests: Request[] = [];
    const environmentId = '00000000-0000-4000-8000-000000000010';
    const projectId = '00000000-0000-4000-8000-000000000001';
    const revisionId = '00000000-0000-4000-8000-000000000013';
    const fetcher: typeof fetch = async (input, init) => {
      const request = new Request(input, init);
      requests.push(request);
      return new Response(
        JSON.stringify({
          id: environmentId,
          project_id: projectId,
          name: 'Production',
          active_revision_id: revisionId,
          created_at: '2030-01-01T12:30:00.000000Z',
          updated_at: '2030-01-01T12:30:01.000000Z',
          active_revision: {
            id: revisionId,
            environment_id: environmentId,
            version: 2,
            schema_version: 1,
            definition: {
              schema_version: 1,
              base_url: 'https://v2.example/',
              variables: {},
              secret_references: [],
              target_policy: {
                schema_version: 1,
                allowed_hostnames: [],
                allowed_cidrs: [],
                denied_hostnames: [],
                denied_cidrs: [],
                allowed_ports: null,
              },
            },
            created_at: '2030-01-01T12:30:01.000000Z',
          },
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json',
            etag: `"environment:${environmentId}:2"`,
          },
        },
      );
    };
    const client = createApiClient(fetcher);

    const result = await client.PATCH('/api/v1/environments/{environment_id}', {
      params: {
        path: { environment_id: environmentId },
        header: { 'if-match': `"environment:${environmentId}:1"` },
      },
      body: { definition: { base_url: 'https://v2.example' } },
    });

    expect(result.data?.active_revision.version).toBe(2);
    expect(requests[0]?.headers.get('if-match')).toBe(
      `"environment:${environmentId}:1"`,
    );
    expect(await requests[0]?.json()).toEqual({
      definition: { base_url: 'https://v2.example' },
    });
  });

  it('returns a typed problem response for a stale environment If-Match', async () => {
    const environmentId = '00000000-0000-4000-8000-000000000010';
    const staleEtag = `"environment:${environmentId}:1"`;
    const problem = {
      type: 'urn:sentinel:problem:revision_conflict',
      title: 'Revision conflict',
      status: 412,
      code: 'revision_conflict',
    } satisfies components['schemas']['Problem'];
    const requests: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      const request = new Request(input, init);
      requests.push(request);
      return new Response(JSON.stringify(problem), {
        status: 412,
        headers: { 'content-type': 'application/problem+json' },
      });
    };
    const client = createApiClient(fetcher);

    const result = await client.PATCH('/api/v1/environments/{environment_id}', {
      params: {
        path: { environment_id: environmentId },
        header: { 'if-match': staleEtag },
      },
      body: { name: 'Stale update' },
    });

    expect(result.data).toBeUndefined();
    expect(result.error?.status).toBe(412);
    expect(result.error?.code).toBe('revision_conflict');
    expect(result.response.status).toBe(412);
    expect(requests[0]?.headers.get('if-match')).toBe(staleEtag);
  });
});
