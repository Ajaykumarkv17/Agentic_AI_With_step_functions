'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { submitTrip } from '@/lib/api';
import styles from './page.module.css';

const PREFERENCE_OPTIONS = ['food', 'culture', 'adventure', 'relaxation', 'shopping', 'sightseeing'] as const;

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [budget, setBudget] = useState('');
  const [preferences, setPreferences] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  function togglePref(p: string) {
    setPreferences(prev => prev.includes(p) ? prev.filter(x => x !== p) : [...prev, p]);
  }

  function validate(): string[] {
    const errs: string[] = [];
    if (!query.trim()) errs.push('Trip description is required');
    if (query.length > 2000) errs.push('Description must be under 2000 characters');
    if (!startDate) errs.push('Start date is required');
    if (!endDate) errs.push('End date is required');
    if (startDate && endDate && startDate > endDate) errs.push('End date must be after start date');
    if (!budget || Number(budget) <= 0) errs.push('Budget must be a positive number');
    return errs;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const errs = validate();
    if (errs.length) { setError(errs.join('. ')); return; }

    setError('');
    setSubmitting(true);
    try {
      const { itinerary_id } = await submitTrip({
        query: query.trim(),
        dates: { start: startDate, end: endDate },
        budget: Number(budget),
        preferences: preferences.length ? preferences : undefined,
      });
      router.push(`/trips/${itinerary_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
      setSubmitting(false);
    }
  }

  const today = new Date().toISOString().split('T')[0];

  return (
    <div className="page-container">
      <section className={styles.hero}>
        <h1 className="animate-in">
          Plan Your <span className={styles.accent}>Perfect</span> Journey
        </h1>
        <p className={`${styles.subtitle} animate-in stagger-1`}>
          AI-powered travel planning tailored for India. Describe your dream trip and let our agents craft a personalized itinerary.
        </p>
      </section>

      <form onSubmit={handleSubmit} className={`${styles.form} animate-in stagger-2`}>
        {/* Query */}
        <div className={styles.field}>
          <label className="label" htmlFor="query">Describe Your Trip</label>
          <textarea
            id="query"
            className="textarea"
            placeholder="e.g. A 5-day family trip to Rajasthan with heritage forts, local cuisine, and camel safari..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            maxLength={2000}
            rows={4}
          />
          <span className={styles.charCount}>{query.length}/2000</span>
        </div>

        {/* Dates */}
        <div className={styles.row}>
          <div className={styles.field}>
            <label className="label" htmlFor="start-date">Start Date</label>
            <input id="start-date" type="date" className="input" value={startDate} onChange={e => setStartDate(e.target.value)} min={today} />
          </div>
          <div className={styles.field}>
            <label className="label" htmlFor="end-date">End Date</label>
            <input id="end-date" type="date" className="input" value={endDate} onChange={e => setEndDate(e.target.value)} min={startDate || today} />
          </div>
        </div>

        {/* Budget */}
        <div className={styles.field}>
          <label className="label" htmlFor="budget">Budget (INR)</label>
          <div className={styles.budgetWrap}>
            <span className={styles.currency}>&#8377;</span>
            <input
              id="budget"
              type="number"
              className="input"
              style={{ paddingLeft: '2rem' }}
              placeholder="50000"
              value={budget}
              onChange={e => setBudget(e.target.value)}
              min={1}
            />
          </div>
        </div>

        {/* Preferences */}
        <div className={styles.field}>
          <label className="label">Preferences (optional)</label>
          <div className={styles.chips}>
            {PREFERENCE_OPTIONS.map(p => (
              <button
                key={p}
                type="button"
                className={`${styles.chip} ${preferences.includes(p) ? styles.chipActive : ''}`}
                onClick={() => togglePref(p)}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        <button type="submit" className="btn btn-primary" disabled={submitting} style={{ width: '100%' }}>
          {submitting ? 'Creating Your Itinerary...' : 'Generate Itinerary'}
        </button>
      </form>
    </div>
  );
}
