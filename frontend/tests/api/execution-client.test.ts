import { describe, expect, it } from 'vitest';
import { createApiClient } from '../../src/shared/api/client';

describe('execution API client', () => {
  it('reads a typed attempt detail without exposing request material', async () => {
    const attemptId = '00000000-0000-4000-8000-000000000008';
    const fetcher: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          id: attemptId,
          sequence: 1,
          state: 'response_received',
          verdict: null,
          created_at: '2030-01-01T12:30:00.000000Z',
          dispatch_recorded_at: '2030-01-01T12:30:00.000000Z',
          response_recorded_at: '2030-01-01T12:30:00.000000Z',
          finished_at: '2030-01-01T12:30:00.000000Z',
          duration_ms: 12,
          dispatch_certainty: 'response_received',
          transport_outcome: 'response_received',
          preparation_error_code: null,
          redirect_rejection_code: null,
          primary_trace_id: null,
          client_span_id: null,
          replayed_by_attempt_id: null,
          included_in_verdict: true,
          links: { self: `/api/v1/attempts/${attemptId}` },
          execution_id: '00000000-0000-4000-8000-000000000006',
          execution_item_id: '00000000-0000-4000-8000-000000000007',
          request_fingerprint: 'a'.repeat(64),
          observation_state: 'available',
          observation: {
            id: attemptId,
            status_code: 200,
            headers: [{ name: 'content-type', value: 'application/json' }],
            body_kind: 'json',
            body: '{"ok":true}',
            captured_bytes: 11,
            truncated: false,
            redaction_unavailable: false,
            recorded_at: '2030-01-01T12:30:00.000000Z',
            expires_at: '2030-01-08T12:30:00.000000Z',
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    const client = createApiClient(fetcher);

    const result = await client.GET('/api/v1/attempts/{attempt_id}', {
      params: { path: { attempt_id: attemptId } },
    });

    expect(result.error).toBeUndefined();
    expect(result.data?.observation_state).toBe('available');
    expect(result.data?.observation?.body).toBe('{"ok":true}');
    expect(result.data?.request_fingerprint).toHaveLength(64);
  });
});
