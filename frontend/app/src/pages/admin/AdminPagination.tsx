/**
 * Shared pagination footer for admin list tables.
 *
 * Every admin list is paginated server-side at 25 rows (see
 * `apps/platform_admin/api/views.py`). Lifted out of the Tenants page, which
 * had this working already, so every other table gets the same control
 * instead of leaving rows past 25 permanently unreachable.
 */
import { Button } from "../../ui";
import { Text } from "../../ui";

interface AdminPaginationProps {
  page: number;
  onPageChange: (page: number) => void;
  hasPrevious: boolean;
  hasNext: boolean;
  label: string;
}

export function AdminPagination({ page, onPageChange, hasPrevious, hasNext, label }: AdminPaginationProps) {
  return (
    <div className="lf-admin-pagination">
      <Text size="sm" tone="secondary">
        {label}
      </Text>
      <div className="lf-inline lf-gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={!hasPrevious}
          onClick={() => onPageChange(Math.max(1, page - 1))}
        >
          Previous
        </Button>
        <Button size="sm" variant="secondary" disabled={!hasNext} onClick={() => onPageChange(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}
