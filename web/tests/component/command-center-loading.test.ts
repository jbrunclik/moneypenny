/**
 * The Command Center's loading state is a skeleton of the real layout.
 */
import { describe, it, expect } from 'vitest';
import { renderCommandCenterLoading } from '@/components/CommandCenter';

describe('renderCommandCenterLoading', () => {
  it('renders skeleton cards in the agents grid instead of a text line', () => {
    const el = renderCommandCenterLoading();
    expect(el.querySelectorAll('.command-center-skeleton-card').length).toBeGreaterThanOrEqual(2);
    expect(el.getAttribute('aria-busy')).toBe('true');
    // Still announced to screen readers
    expect(el.querySelector('.visually-hidden')?.textContent).toContain('Loading agents');
  });
});
