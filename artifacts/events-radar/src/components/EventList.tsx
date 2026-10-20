import { useState, useCallback } from 'react';
import type { EventWithOpportunita, StatoOpportunita } from '@workspace/api-client-react';
import { format, parseISO } from 'date-fns';
import { getTipoColor, TIPO_LABELS } from '../lib/eventColors';
import { saveOpportunita } from '../lib/opportunita';

const formatTipo = (tipo: string) =>
  TIPO_LABELS[tipo] ?? tipo.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());

function isPastEvent(event: EventWithOpportunita): boolean {
  // Data locale (non UTC) per coerenza con cio che l'utente vede a schermo
  const today = format(new Date(), 'yyyy-MM-dd');
  if (event.dataFine != null) return event.dataFine < today;
  if (event.dataInizio != null) return event.dataInizio < today;
  return false;
}

const STATO_LABELS: Record<string, string> = {
  non_contattato: 'Non contattato',
  contattato: 'Contattato',
  risposto: 'Risposto',
  non_risposto: 'Non risposto',
  archiviato: 'Archiviato',
};

const STATO_ORDER: StatoOpportunita[] = [
  'non_contattato',
  'contattato',
  'risposto',
  'non_risposto',
  'archiviato',
];

function EventCard({ event }: { event: EventWithOpportunita }) {
  const [stato, setStato] = useState<StatoOpportunita>(event.opportunita?.stato || 'non_contattato');
  const [note, setNote] = useState(event.opportunita?.note || '');
  const [saved, setSaved] = useState(false);

  const handleSave = useCallback((newStato: StatoOpportunita, newNote: string) => {
    saveOpportunita(event.id, newStato, newNote);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }, [event.id]);

  const handleStatoClick = (newStato: StatoOpportunita) => {
    if (newStato === stato) return;
    setStato(newStato);
    handleSave(newStato, note);
  };

  const handleNoteBlur = () => {
    if (note !== (event.opportunita?.note || '')) {
      handleSave(stato, note);
    }
  };

  const past = isPastEvent(event);

  return (
    <div className={past ? 'event-card event-card-past' : 'event-card'}>
      <div className="badges-row">
        <span className={`badge bg-${event.tipoEvento}`} style={{display: 'flex', alignItems: 'center', gap: 5}}>
          <span className="tipo-dot" style={{background: getTipoColor(event.tipoEvento)}} />
          {formatTipo(event.tipoEvento)}
        </span>
        <span className={`badge bg-${stato}`}>{STATO_LABELS[stato] ?? stato}</span>
        {(!event.lat || !event.lng || event.luogo === 'Online' || event.luogo === 'online') && (
          <span className="badge" style={{background: 'var(--color-mid-gray)'}}>In linea</span>
        )}
        {past && <span className="badge bg-archiviato">Passato</span>}
      </div>
      
      <h3 className="event-title">{event.titolo}</h3>
      
      <p className="event-details">
        {event.dataInizio ? format(parseISO(event.dataInizio), 'dd/MM/yyyy') : 'Data da confermare'}
        {event.luogo && event.luogo !== 'Online' && event.luogo !== 'online' ? ` — ${event.luogo}` : ''}
      </p>
      
      {event.organizzatore && (
        <p className="event-details">{event.organizzatore}</p>
      )}

      <div className="event-footer">
        <span>{event.creditiFormativi ? `${event.creditiFormativi} CFP` : ''}</span>
        {event.urlSorgente && (
          <a href={event.urlSorgente} target="_blank" rel="noopener noreferrer" className="event-source-link" aria-label={`Vai alla fonte di ${event.titolo}`}>
            Vai alla fonte &rarr;
          </a>
        )}
      </div>

      <div className="status-pills" role="group" aria-label={`Stato opportunità per ${event.titolo}`}>
        {STATO_ORDER.map((s) => (
          <button
            key={s}
            className={`status-pill status-pill--${s}${stato === s ? ' status-pill--active' : ''}`}
            onClick={() => handleStatoClick(s)}
            aria-pressed={stato === s}
            type="button"
          >
            {STATO_LABELS[s]}
          </button>
        ))}
      </div>

      {event.opportunita?.dataUltimoAggiornamento && (
        <p className="timestamp-aggiornamento">
          Aggiornato il {format(parseISO(event.opportunita.dataUltimoAggiornamento), 'dd/MM/yyyy HH:mm')}
        </p>
      )}

      <textarea
        className="notes-field"
        placeholder="Note opportunità..."
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onBlur={handleNoteBlur}
        aria-label={`Note per ${event.titolo}`}
      />
      {saved && <div className="save-feedback">Salvato</div>}
    </div>
  );
}

export default function EventList({ events }: { events: EventWithOpportunita[] }) {
  const confirmedEvents = events.filter(e => e.dataInizio);
  const unconfirmedEvents = events.filter(e => !e.dataInizio);

  return (
    <>
      {confirmedEvents.map(event => (
        <EventCard key={event.id} event={event} />
      ))}
      
      {unconfirmedEvents.length > 0 && (
        <>
          <h4 className="heading" style={{ fontSize: '16px', marginTop: '16px' }}>Date da confermare</h4>
          {unconfirmedEvents.map(event => (
            <EventCard key={event.id} event={event} />
          ))}
        </>
      )}
    </>
  );
}
