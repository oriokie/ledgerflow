import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";
import type { Anomaly } from "../../api/types";
import { anomalyView } from "./insightsCopy";

/** Anomalies as plain "worth a look" notes rather than model output — a human
 * headline, the specifics, and a way to see the transaction. */
export function AnomalyList({ anomalies }: { anomalies: Anomaly[] }) {
  return (
    <div>
      {anomalies.map((a, i) => {
        const v = anomalyView(a);
        return (
          <div key={a.transaction_id ?? i} className={`lf-worth lf-tone-${v.tone}`}>
            <AlertTriangle size={18} strokeWidth={1.8} className="lf-worth-icon" aria-hidden="true" />
            <div>
              <div className="lf-worth-headline">{v.headline}</div>
              <div className="lf-worth-body">
                {a.explanation}
                {a.transaction_id && (
                  <>
                    {" · "}
                    <Link to="/transactions">view transactions</Link>
                  </>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
