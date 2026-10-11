/**
 * Artifact API: a version's HTML for the sandboxed frame, and saved state.
 */
import type { ArtifactVersion } from '../types/api';
import { request, requestWithRetry } from './http';

export function fetchArtifactVersion(id: string, version: number): Promise<ArtifactVersion> {
  return requestWithRetry<ArtifactVersion>(
    `/api/artifacts/${encodeURIComponent(id)}/versions/${version}`
  );
}

export async function saveArtifactState(id: string, state: unknown): Promise<void> {
  await request<{ status: string }>(`/api/artifacts/${encodeURIComponent(id)}/state`, {
    method: 'PUT',
    body: JSON.stringify({ state: state ?? null }),
  });
}
