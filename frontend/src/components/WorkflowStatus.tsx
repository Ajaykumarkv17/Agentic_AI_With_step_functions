'use client';

import { useEffect, useState, useCallback } from 'react';
import { getWorkflowStatus } from '@/lib/api';
import { WorkflowStatus, AgentStatus } from '@/types';
import styles from './WorkflowStatus.module.css';

const AGENTS: { key: keyof WorkflowStatus['agents']; label: string; icon: string }[] = [
  { key: 'destination_researcher', label: 'Destination Research', icon: '🗺' },
  { key: 'budget_optimizer', label: 'Budget Optimization', icon: '💰' },
  { key: 'weather_analyzer', label: 'Weather Analysis', icon: '🌤' },
  { key: 'experience_curator', label: 'Experience Curation', icon: '🎭' },
];

const STATUS_LABEL: Record<AgentStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  fallback: 'Fallback',
};

interface Props {
  itineraryId: string;
  onComplete: () => void;
}

export default function WorkflowStatusView({ itineraryId, onComplete }: Props) {
  const [status, setStatus] = useState<WorkflowStatus | null>(null);
  const [error, setError] = useState('');

  const poll = useCallback(async () => {
    try {
      const data = await getWorkflowStatus(itineraryId);
      setStatus(data);
      if (data.status === 'completed' || data.status === 'failed') {
        onComplete();
      }
      return data.status === 'completed' || data.status === 'failed';
    } catch {
      setError('Unable to fetch workflow status');
      return false;
    }
  }, [itineraryId, onComplete]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;

    async function tick() {
      if (cancelled) return;
      const done = await poll();
      if (!done && !cancelled) timer = setTimeout(tick, 4000);
    }
    tick();

    return () => { cancelled = true; clearTimeout(timer); };
  }, [poll]);

  const overallLabel = status?.status === 'completed' ? 'Itinerary Ready'
    : status?.status === 'failed' ? 'Workflow Failed'
    : 'Generating Your Itinerary...';

  return (
    <section className={styles.wrapper}>
      <h2 className={`${styles.heading} animate-in`}>{overallLabel}</h2>
      {status?.status !== 'completed' && status?.status !== 'failed' && (
        <p className={`${styles.sub} animate-in stagger-1`}>Our AI agents are working in parallel to craft your perfect trip.</p>
      )}

      <div className={styles.grid}>
        {AGENTS.map((agent, i) => {
          const agentStatus: AgentStatus = status?.agents?.[agent.key] ?? 'pending';
          return (
            <div key={agent.key} className={`${styles.card} ${styles[agentStatus]} animate-in stagger-${i + 1}`}>
              <div className={styles.cardIcon}>{agent.icon}</div>
              <h4 className={styles.cardTitle}>{agent.label}</h4>
              <span className={`badge badge-${agentStatus}`}>
                {agentStatus === 'running' && <span className={styles.dot} />}
                {STATUS_LABEL[agentStatus]}
              </span>
              {agentStatus === 'running' && <div className={styles.progress} />}
            </div>
          );
        })}
      </div>

      {/* Pipeline visualization */}
      {status && (
        <div className={`${styles.pipeline} animate-in stagger-5`}>
          <PipelineStep label="Submitted" done />
          <PipelineConnector />
          <PipelineStep label="Agents" done={['merging', 'completed'].includes(status.status)} active={status.status === 'agents_running' || status.status === 'started'} />
          <PipelineConnector />
          <PipelineStep label="Merging" done={status.status === 'completed'} active={status.status === 'merging'} />
          <PipelineConnector />
          <PipelineStep label="Complete" done={status.status === 'completed'} />
        </div>
      )}

      {error && <div className="notice">{error}</div>}
    </section>
  );
}

function PipelineStep({ label, done, active }: { label: string; done: boolean; active?: boolean }) {
  const cls = done ? styles.stepDone : active ? styles.stepActive : styles.stepPending;
  return (
    <div className={`${styles.step} ${cls}`}>
      <div className={styles.stepDot} />
      <span className={styles.stepLabel}>{label}</span>
    </div>
  );
}

function PipelineConnector() {
  return <div className={styles.connector} />;
}
