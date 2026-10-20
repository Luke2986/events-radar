import { useListFonti } from '@workspace/api-client-react';
import { format, parseISO } from 'date-fns';

export default function SourcesPanel() {
  const { data, isLoading } = useListFonti({
    query: { enabled: true, queryKey: ['/api/fonti'] }
  });

  return (
    <div className="sources-panel">
      <h2 className="sources-title heading">Monitoraggio fonti</h2>
      
      {isLoading ? (
        <div className="sources-grid">
          {Array.from({length: 4}).map((_, i) => (
            <div key={i} className="loading-skeleton" style={{height: 24, width: '100%'}}></div>
          ))}
        </div>
      ) : (
        <div className="sources-grid">
          {data?.fonti.map(fonte => (
            <div key={fonte.id} className="source-item">
              <span className={`status-dot dot-${fonte.statoScraper}`} title={`Stato: ${fonte.statoScraper}`}></span>
              <strong>{fonte.nome}</strong>
              <span style={{color: 'var(--color-dark-gray)'}}>({fonte.paese})</span>
              {fonte.ultimoScrape && (
                <span style={{color: 'var(--color-dark-gray)', marginLeft: 'auto'}}>
                  {format(parseISO(fonte.ultimoScrape), 'dd/MM/yyyy')}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
