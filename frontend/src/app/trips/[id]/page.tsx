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

  // Try loading itinerary on mount — if already complete, skip workflow view
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

  return (
    <div className="page-container">
      {/* Header */}
      <header className={`${styles.header} animate-in`}>
        <h1>Your Itinerary</h1>
        <p className={styles.meta}>
          {itinerary.days.length} days &middot; {formatINR(itinerary.summary?.total_cost_inr ?? 0)} total &middot; {itinerary.summary?.budget_tier_selected ?? ''} tier
        </p>
      </header>

      {/* Notices */}
      {(itinerary.notices?.length ?? 0) > 0 && (
        <div className={`${styles.notices} animate-in stagger-1`}>
          {itinerary.notices.map((n, i) => <NoticeCard key={i} notice={n} />)}
        </div>
      )}

      {/* Day-by-day */}
      <div className={styles.days}>
        {itinerary.days.map((day, i) => (
          <DayCard key={day.date} day={day} index={i} />
        ))}
      </div>

      {/* Summary */}
      <SummarySection summary={itinerary.summary} />
    </div>
  );
}

/* ── Day Card ── */
function DayCard({ day, index }: { day: DayPlan; index: number }) {
  const [expanded, setExpanded] = useState(index === 0);

  return (
    <article className={`${styles.dayCard} animate-in`} style={{ animationDelay: `${index * 0.06}s` }}>
      <button className={styles.dayHeader} onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <div>
          <h3 className={styles.dayTitle}>Day {index + 1} — {day.destination}</h3>
          <span className={styles.dayDate}>{formatDate(day.date)}</span>
        </div>
        <div className={styles.dayMeta}>
          <span className={styles.weather}>
            {day.weather.conditions} &middot; {day.weather.temp_min}°–{day.weather.temp_max}°C
            {Number(day.weather.precipitation_pct) > 50 && ' 🌧'}
          </span>
          <span className={styles.dayCost}>{formatINR(day.day_cost_inr)}</span>
          <span className={styles.chevron}>{expanded ? '▾' : '▸'}</span>
        </div>
      </button>

      {expanded && (
        <div className={styles.dayBody}>
          {day.weather.advisory && <div className="notice">{day.weather.advisory}</div>}

          <div className={styles.slots}>
            {(Object.keys(SLOT_LABELS) as Array<keyof typeof SLOT_LABELS>).map(slot => (
              <SlotCard key={slot} label={SLOT_LABELS[slot]} activity={day.slots[slot]} />
            ))}
          </div>

          {day.transport && (
            <div className={styles.transport}>
              <span className={styles.transportIcon}>🚆</span>
              {day.transport.mode} from {day.transport.from} → {day.transport.to} &middot; {day.transport.duration_hours}h &middot; {formatINR(day.transport.cost_inr)}
            </div>
          )}

          {day.accommodation && (
            <div className={styles.accommodation}>
              <span className={styles.transportIcon}>🏨</span>
              {day.accommodation.name} ({day.accommodation.type}) &middot; {formatINR(day.accommodation.cost_per_night_inr)}/night
            </div>
          )}
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
      {activity.is_festival_event && <span className={`badge badge-running`} style={{ marginTop: 8 }}>Festival Event</span>}
    </div>
  );
}

/* ── Notice ── */
function NoticeCard({ notice }: { notice: Notice }) {
  return <div className="notice"><strong>{notice.section}:</strong> {notice.message}</div>;
}

/* ── Summary ── */
function SummarySection({ summary }: { summary: Itinerary['summary'] }) {
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
      </div>

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
          <h3>Highlighted Experiences</h3>
          <ul className={styles.list}>
            {summary.highlighted_experiences.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </div>
      )}
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
