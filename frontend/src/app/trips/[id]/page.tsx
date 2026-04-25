'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { getItinerary } from '@/lib/api';
import { Itinerary, DayPlan, ActivitySlot, Notice } from '@/types';
import WorkflowStatusView from '@/components/WorkflowStatus';
import styles from './page.module.css';

const SLOT_LABELS = { morning: 'Morning', afternoon: 'Afternoon', evening: 'Evening' } as const;
const TYPE_ICONS: Record<string, string> = {
  food: '🍽', culture: '🏛', adventure: '⛰', relaxation: '🧘',
  shopping: '🛍', transit: '🚂', sightseeing: '📸',
};
const TRANSPORT_ICONS: Record<string, string> = {
  flight: '✈', train: '🚆', bus: '🚌', car: '🚗',
};
const WEATHER_ICONS: Record<string, string> = {
  sunny: '☀', clear: '☀', warm: '🌤', hot: '🔥',
  rain: '🌧', cloudy: '☁', storm: '⛈', cold: '❄', default: '🌤',
};

function getWeatherIcon(conditions: string): string {
  const lower = conditions.toLowerCase();
  for (const [key, icon] of Object.entries(WEATHER_ICONS)) {
    if (key !== 'default' && lower.includes(key)) return icon;
  }
  return WEATHER_ICONS.default;
}

export default function TripPage() {
  const { id } = useParams<{ id: string }>();
  const [itinerary, setItinerary] = useState<Itinerary | null>(null);
  const [phase, setPhase] = useState<'workflow' | 'itinerary'>('workflow');
  const [error, setError] = useState('');

  const loadItinerary = useCallback(async () => {
    try {
      const data = await getItinerary(id);
      setItinerary(data);
      setPhase('itinerary');
    } catch {
      setError('Unable to load itinerary. It may still be generating.');
    }
  }, [id]);

  useEffect(() => {
    getItinerary(id).then(data => {
      if (data?.days?.length) { setItinerary(data); setPhase('itinerary'); }
    }).catch(() => { /* still generating */ });
  }, [id]);

  const handleWorkflowComplete = useCallback(() => {
    loadItinerary();
  }, [loadItinerary]);

  if (phase === 'workflow') {
    return (
      <div className="page-container">
        <WorkflowStatusView itineraryId={id} onComplete={handleWorkflowComplete} />
        {error && <div className="notice" style={{ marginTop: 'var(--space-md)' }}>{error}</div>}
      </div>
    );
  }

  if (!itinerary?.days?.length) {
    return (
      <div className="page-container" style={{ textAlign: 'center', paddingTop: '4rem' }}>
        <p style={{ color: 'var(--color-text-muted)' }}>Loading your itinerary...</p>
      </div>
    );
  }

  // Derive source city from first day's transport
  const firstTransport = itinerary.days.find(d => d.transport)?.transport;
  const sourceCity = firstTransport?.from ?? null;
  const destCity = itinerary.days[0]?.destination ?? '';
  const totalBudget = Number(itinerary.trip_request?.budget ?? 0);
  const totalCost = Number(itinerary.summary?.total_cost_inr ?? 0);
  const budgetPct = totalBudget > 0 ? Math.min((totalCost / totalBudget) * 100, 100) : 0;

  return (
    <div className="page-container">
      {/* Header */}
      <header className={`${styles.header} animate-in`}>
        <h1>Your Itinerary</h1>
        <p className={styles.meta}>
          {itinerary.days.length} days &middot; {formatINR(itinerary.summary?.total_cost_inr ?? 0)} total &middot; {itinerary.summary?.budget_tier_selected ?? ''} tier
        </p>
      </header>

      {/* Route Banner — shows source → destination */}
      {sourceCity && (
        <div className={`${styles.routeBanner} animate-in stagger-1`}>
          <div className={styles.routeEndpoint}>
            <span className={styles.routeLabel}>From</span>
            <span className={styles.routeCity}>{sourceCity}</span>
          </div>
          <div className={styles.routeLine}>
            <div className={styles.routeDots}>
              <span className={styles.routeIcon}>
                {TRANSPORT_ICONS[firstTransport?.mode ?? 'train'] ?? '✈'}
              </span>
            </div>
            <span className={styles.routeDetail}>
              {firstTransport?.mode} &middot; {firstTransport?.duration_hours}h &middot; {formatINR(firstTransport?.cost_inr ?? 0)}
            </span>
          </div>
          <div className={styles.routeEndpoint}>
            <span className={styles.routeLabel}>To</span>
            <span className={styles.routeCity}>{destCity}</span>
          </div>
        </div>
      )}

      {/* Quick Info Bar */}
      <div className={`${styles.tripInfoBar} animate-in stagger-2`}>
        <div className={styles.tripInfoItem}>
          <span className={styles.tripInfoIcon}>📅</span>
          <span className={styles.tripInfoValue}>{itinerary.days.length}</span>
          <span className={styles.tripInfoLabel}>Days</span>
        </div>
        <div className={styles.tripInfoItem}>
          <span className={styles.tripInfoIcon}>📍</span>
          <span className={styles.tripInfoValue}>{destCity}</span>
          <span className={styles.tripInfoLabel}>Destination</span>
        </div>
        <div className={styles.tripInfoItem}>
          <span className={styles.tripInfoIcon}>💰</span>
          <span className={styles.tripInfoValue}>{formatINR(totalCost)}</span>
          <span className={styles.tripInfoLabel}>Total Cost</span>
        </div>
        <div className={styles.tripInfoItem}>
          <span className={styles.tripInfoIcon}>🏷</span>
          <span className={styles.tripInfoValue} style={{ textTransform: 'capitalize' }}>{itinerary.summary?.budget_tier_selected}</span>
          <span className={styles.tripInfoLabel}>Budget Tier</span>
        </div>
      </div>

      {/* Notices */}
      {(itinerary.notices?.length ?? 0) > 0 && (
        <div className={`${styles.notices} animate-in stagger-3`}>
          {itinerary.notices.map((n, i) => <NoticeCard key={i} notice={n} />)}
        </div>
      )}

      {/* Day-by-day timeline */}
      <div className={styles.days}>
        {itinerary.days.map((day, i) => (
          <DayCard key={day.date} day={day} index={i} />
        ))}
      </div>

      {/* Summary */}
      <SummarySection summary={itinerary.summary} totalBudget={totalBudget} totalCost={totalCost} budgetPct={budgetPct} />
    </div>
  );
}


/* ── Day Card ── */
function DayCard({ day, index }: { day: DayPlan; index: number }) {
  const [expanded, setExpanded] = useState(index === 0);

  return (
    <article className={`${styles.dayCard} animate-in`} style={{ animationDelay: `${index * 0.08}s` }}>
      <span className={styles.dayMarker}>{index + 1}</span>
      <button className={styles.dayHeader} onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <div className={styles.dayHeaderLeft}>
          <h3 className={styles.dayTitle}>Day {index + 1} — {day.destination}</h3>
          <span className={styles.dayDate}>{formatDate(day.date)}</span>
        </div>
        <div className={styles.dayMeta}>
          <span className={styles.weatherPill}>
            <span className={styles.weatherIcon}>{getWeatherIcon(day.weather.conditions)}</span>
            {day.weather.temp_min}°–{day.weather.temp_max}°C
            {Number(day.weather.precipitation_pct) > 50 && ' 🌧'}
          </span>
          <span className={styles.dayCost}>{formatINR(day.day_cost_inr)}</span>
          <span className={`${styles.chevron} ${expanded ? styles.chevronOpen : ''}`}>▸</span>
        </div>
      </button>

      {expanded && (
        <div className={styles.dayBody}>
          {day.weather.advisory && (
            <div className={styles.weatherAdvisory}>
              <span>💡</span> {day.weather.advisory}
            </div>
          )}

          <div className={styles.slots}>
            {(Object.keys(SLOT_LABELS) as Array<keyof typeof SLOT_LABELS>).map(slot => (
              <SlotCard key={slot} label={SLOT_LABELS[slot]} activity={day.slots[slot]} />
            ))}
          </div>

          <div className={styles.logisticsRow}>
            {day.transport && (
              <div className={`${styles.logisticsCard} ${!day.accommodation ? styles.logisticsCardFull : ''}`}>
                <div className={styles.logisticsIcon}>
                  {TRANSPORT_ICONS[day.transport.mode] ?? '🚆'}
                </div>
                <div className={styles.logisticsContent}>
                  <span className={styles.logisticsTitle}>
                    {day.transport.from} → {day.transport.to}
                  </span>
                  <span className={styles.logisticsDetail}>
                    {day.transport.mode} &middot; {day.transport.duration_hours}h
                  </span>
                  <span className={styles.logisticsCost}>{formatINR(day.transport.cost_inr)}</span>
                </div>
              </div>
            )}

            {day.accommodation && (
              <div className={`${styles.logisticsCard} ${!day.transport ? styles.logisticsCardFull : ''}`}>
                <div className={styles.logisticsIcon}>🏨</div>
                <div className={styles.logisticsContent}>
                  <span className={styles.logisticsTitle}>{day.accommodation.name}</span>
                  <span className={styles.logisticsDetail}>{day.accommodation.type}</span>
                  <span className={styles.logisticsCost}>{formatINR(day.accommodation.cost_per_night_inr)}/night</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

/* ── Slot Card ── */
function SlotCard({ label, activity }: { label: string; activity: ActivitySlot }) {
  return (
    <div className={`${styles.slot} ${activity.is_festival_event ? styles.slotFestival : ''}`}>
      <div className={styles.slotHeader}>
        <span className={styles.slotTime}>{label}</span>
        <span className={styles.slotType}>{TYPE_ICONS[activity.type] || '📌'} {activity.type}</span>
      </div>
      <h4 className={styles.slotTitle}>{activity.activity}</h4>
      <p className={styles.slotDesc}>{activity.description}</p>
      <span className={styles.slotCost}>{formatINR(activity.estimated_cost_inr)}</span>
      {activity.is_festival_event && <span className="badge badge-running" style={{ marginTop: 8, alignSelf: 'flex-start' }}>Festival Event</span>}
    </div>
  );
}

/* ── Notice ── */
function NoticeCard({ notice }: { notice: Notice }) {
  return <div className="notice"><strong>{notice.section}:</strong> {notice.message}</div>;
}

/* ── Summary ── */
function SummarySection({ summary, totalBudget, totalCost, budgetPct }: {
  summary: Itinerary['summary'];
  totalBudget: number;
  totalCost: number;
  budgetPct: number;
}) {
  return (
    <section className={`${styles.summary} animate-in`}>
      <h2>Trip Summary</h2>

      <div className={styles.summaryGrid}>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Total Cost</span>
          <span className={styles.summaryValue}>{formatINR(summary.total_cost_inr)}</span>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Budget Tier</span>
          <span className={styles.summaryValue} style={{ textTransform: 'capitalize' }}>{summary.budget_tier_selected}</span>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Savings</span>
          <span className={styles.summaryValue} style={{ color: 'var(--color-success)' }}>
            {totalBudget > 0 ? formatINR(totalBudget - totalCost) : '—'}
          </span>
        </div>
      </div>

      {/* Budget utilization bar */}
      {totalBudget > 0 && (
        <div className={styles.budgetBar}>
          <div className={styles.budgetBarHeader}>
            <span className={styles.budgetBarLabel}>Budget Utilization</span>
            <span className={styles.budgetBarAmount}>{budgetPct.toFixed(0)}% used</span>
          </div>
          <div className={styles.budgetTrack}>
            <div className={styles.budgetFill} style={{ width: `${budgetPct}%` }} />
          </div>
          <div className={styles.budgetLabels}>
            <span>Spent: {formatINR(totalCost)}</span>
            <span>Budget: {formatINR(totalBudget)}</span>
          </div>
        </div>
      )}

      <div className={styles.summaryColumns} style={{ marginTop: 'var(--space-xl)' }}>
        {summary.packing_advisory?.length > 0 && (
          <div className={styles.summarySection}>
            <h3>Packing Advisory</h3>
            <ul className={styles.list}>
              {summary.packing_advisory.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          </div>
        )}

        {summary.highlighted_experiences?.length > 0 && (
          <div className={styles.summarySection}>
            <h3>Top Experiences</h3>
            <ul className={styles.experienceList}>
              {summary.highlighted_experiences.map((item, i) => (
                <li key={i} className={styles.experienceItem}>
                  <span className={styles.experienceNumber}>{i + 1}</span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

/* ── Helpers ── */
function formatINR(n: number | string): string {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(Number(n));
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}
