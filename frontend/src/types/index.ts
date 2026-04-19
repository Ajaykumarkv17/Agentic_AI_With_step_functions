// ── Trip Request ──

export interface TripRequest {
  query: string;
  dates: {
    start: string;
    end: string;
  };
  budget: number;
  preferences?: string[];
}

// ── Itinerary ──

export interface Itinerary {
  itinerary_id: string;
  trip_request: TripRequest;
  days: DayPlan[];
  summary: ItinerarySummary;
  notices: Notice[];
  created_at: string;
}

export interface ItinerarySummary {
  total_cost_inr: number;
  packing_advisory: string[];
  highlighted_experiences: string[];
  budget_tier_selected: "economy" | "comfort";
}

export interface DayPlan {
  date: string;
  destination: string;
  weather: DayWeather;
  slots: {
    morning: ActivitySlot;
    afternoon: ActivitySlot;
    evening: ActivitySlot;
  };
  transport?: TransportDetail;
  accommodation: AccommodationDetail;
  day_cost_inr: number;
}

export interface DayWeather {
  temp_min: number;
  temp_max: number;
  precipitation_pct: number;
  conditions: string;
  advisory?: string;
}

export interface ActivitySlot {
  activity: string;
  type: "food" | "culture" | "adventure" | "relaxation" | "shopping" | "transit" | "sightseeing";
  description: string;
  estimated_cost_inr: number;
  is_festival_event?: boolean;
}

export interface TransportDetail {
  mode: "train" | "flight" | "bus" | "car";
  from: string;
  to: string;
  duration_hours: number;
  cost_inr: number;
}

export interface AccommodationDetail {
  name: string;
  type: "hotel" | "hostel" | "homestay" | "resort";
  cost_per_night_inr: number;
}

export interface Notice {
  section: string;
  message: string;
  type: "fallback_data" | "stale_data" | "best_effort";
}

// ── Workflow Status ──

export interface WorkflowStatus {
  itinerary_id: string;
  status: "started" | "agents_running" | "merging" | "completed" | "failed";
  agents: {
    destination_researcher: AgentStatus;
    budget_optimizer: AgentStatus;
    weather_analyzer: AgentStatus;
    experience_curator: AgentStatus;
  };
  updated_at: string;
}

export type AgentStatus = "pending" | "running" | "completed" | "failed" | "fallback";
