import { TripRequest, Itinerary, WorkflowStatus } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  return res.json();
}

export function submitTrip(trip: TripRequest): Promise<{ itinerary_id: string }> {
  return request('/trips', { method: 'POST', body: JSON.stringify(trip) });
}

export function getItinerary(id: string): Promise<Itinerary> {
  return request<any>(`/trips/${id}`).then(data => {
    // The API returns the raw DynamoDB item where the merged itinerary
    // is nested under an "itinerary" key. Flatten it to the top level.
    if (data?.itinerary?.days) {
      return { ...data, ...data.itinerary } as Itinerary;
    }
    return data as Itinerary;
  });
}

export function getWorkflowStatus(id: string): Promise<WorkflowStatus> {
  return request(`/trips/${id}/status`);
}
