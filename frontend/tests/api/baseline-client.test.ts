import { describe, expect, it } from 'vitest';
import { createApiClient } from '../../src/shared/api/client';

const testCaseId = '00000000-0000-4000-8000-000000000001';
const environmentId = '00000000-0000-4000-8000-000000000002';
const baselineId = '00000000-0000-4000-8000-000000000003';

describe('baseline API client', () => {
  it('sends the typed activation command with its strong precondition', async () => {
    const requests: Request[] = [];
    const client = createApiClient(async (input, init) => {
      requests.push(new Request(input, init));
      return new Response(
        JSON.stringify({
          id: '00000000-0000-4000-8000-000000000004',
          test_case_id: testCaseId,
          environment_id: environmentId,
          baseline_id: baselineId,
          baseline_version: 1,
          activated_at: '2030-01-01T12:30:00.000000Z',
          deactivated_at: null,
          reason: null,
        }),
        {
          status: 201,
          headers: { 'content-type': 'application/json', etag: '"scope-2"' },
        },
      );
    });

    const result = await client.POST(
      '/api/v1/test-cases/{test_case_id}/baseline-activations',
      {
        params: {
          path: { test_case_id: testCaseId },
          header: { 'If-Match': '"scope-1"' },
        },
        body: {
          environment_id: environmentId,
          baseline_id: baselineId,
          reason: null,
        },
      },
    );

    expect(result.error).toBeUndefined();
    expect(result.data?.baseline_id).toBe(baselineId);
    expect(requests[0]?.headers.get('if-match')).toBe('"scope-1"');
    expect(await requests[0]?.json()).toEqual({
      environment_id: environmentId,
      baseline_id: baselineId,
      reason: null,
    });
  });

  it('reads a typed baseline page and preserves the scope ETag', async () => {
    const client = createApiClient(
      async () =>
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'content-type': 'application/json', etag: '"scope-1"' },
        }),
    );

    const result = await client.GET(
      '/api/v1/test-cases/{test_case_id}/baselines',
      {
        params: {
          path: { test_case_id: testCaseId },
          query: { environment_id: environmentId },
        },
      },
    );

    expect(result.data?.items).toEqual([]);
    expect(result.response.headers.get('etag')).toBe('"scope-1"');
  });
});
