/**
 * Gestures module.
 * Handles touch gestures and swipe handling for mobile.
 */

import { toggleSidebar, closeSidebar } from '../components/Sidebar';
import { getElementById } from '../utils/dom';
import { createSwipeHandler, isTouchDevice, resetSwipeStates } from '../gestures/swipe';

/**
 * Setup touch gestures for mobile devices.
 */
export function setupTouchGestures(): void {
  if (!isTouchDevice()) return;

  const conversationsList = getElementById('conversations-list');
  const sidebar = getElementById('sidebar');
  const main = document.querySelector('.main') as HTMLElement | null;

  if (!conversationsList || !sidebar || !main) return;

  // Constants
  const SWIPE_THRESHOLD = 60;
  const SWIPE_DISTANCE = 160; // Updated from 80 to accommodate both rename and delete buttons
  const EDGE_ZONE = 50; // px from left edge to trigger sidebar swipe

  // Track active swipe type to prevent conflicts
  let activeSwipeType: 'none' | 'conversation' | 'sidebar' = 'none';

  // Swipe to reveal rename and delete on conversations
  const conversationSwipe = createSwipeHandler({
    shouldStart: (e) => {
      if (activeSwipeType === 'sidebar') return false;
      const wrapper = (e.target as HTMLElement).closest('.conversation-item-wrapper');
      if (!wrapper) {
        resetSwipeStates();
        return false;
      }
      // Prevent starting new swipe if clicking action buttons
      if ((e.target as HTMLElement).closest('.conversation-rename-swipe')) return false;
      if ((e.target as HTMLElement).closest('.conversation-delete-swipe')) return false;
      // Note: We set activeSwipeType in onSwipeMove (when actual swiping starts),
      // not here, to avoid blocking sidebar swipes after a tap (non-swipe touch)
      return true;
    },
    getTarget: (e) => {
      const wrapper = (e.target as HTMLElement).closest('.conversation-item-wrapper');
      return wrapper?.querySelector('.conversation-item') as HTMLElement | null;
    },
    getTransform: (deltaX, isOpen, { maxDistance }) => {
      if (isOpen && deltaX < 0) {
        const translateX = Math.max(deltaX + maxDistance, 0);
        return `translateX(-${translateX}px)`;
      } else if (!isOpen && deltaX > 0) {
        const translateX = Math.min(deltaX, maxDistance);
        return `translateX(-${translateX}px)`;
      }
      return null;
    },
    getInitialState: (target) => {
      return target?.closest('.conversation-item-wrapper')?.classList.contains('swiped') || false;
    },
    onSwipeMove: () => {
      // Mark as conversation swipe once actual swiping starts
      // This prevents sidebar swipes from interfering mid-gesture
      activeSwipeType = 'conversation';
    },
    onComplete: (target, deltaX) => {
      activeSwipeType = 'none';
      const wrapper = target.closest('.conversation-item-wrapper');
      if (!wrapper) return;

      const isOpen = wrapper.classList.contains('swiped');
      if (isOpen && deltaX < -SWIPE_THRESHOLD) {
        wrapper.classList.remove('swiped');
      } else if (!isOpen && deltaX > SWIPE_THRESHOLD) {
        resetSwipeStates(wrapper as HTMLElement);
        wrapper.classList.add('swiped');
      }
    },
    onSnapBack: (target) => {
      activeSwipeType = 'none';
      const wrapper = target.closest('.conversation-item-wrapper');
      wrapper?.classList.remove('swiped');
    },
    threshold: SWIPE_THRESHOLD,
    maxDistance: SWIPE_DISTANCE,
  });

  conversationsList.addEventListener('touchstart', conversationSwipe.handleTouchStart, { passive: true });
  conversationsList.addEventListener('touchmove', conversationSwipe.handleTouchMove, { passive: true });
  conversationsList.addEventListener('touchend', conversationSwipe.handleTouchEnd, { passive: true });
  conversationsList.addEventListener('touchcancel', conversationSwipe.handleTouchCancel, { passive: true });

  // Sidebar edge swipe - swipe from left edge to open, swipe left to close
  let sidebarSwipeStartX = 0;
  let sidebarSwipeCurrentX = 0;
  let isSidebarSwiping = false;
  const sidebarWidth = 280; // matches CSS --sidebar-width

  const handleSidebarTouchStart = (e: TouchEvent): void => {
    if (activeSwipeType === 'conversation') return;

    const target = e.target as HTMLElement;
    const startX = e.touches[0].clientX;
    const isSidebarOpen = sidebar.classList.contains('open');

    // Don't start sidebar swipe if touching a conversation item (let conversation swipe handle it)
    if (target.closest('.conversation-item-wrapper')) {
      // Reset activeSwipeType if it was stuck on 'sidebar' from a previous incomplete swipe
      if (activeSwipeType === 'sidebar') {
        activeSwipeType = 'none';
      }
      return;
    }

    // Start swipe if:
    // - Closed: in edge zone (swipe right to open)
    // - Open: anywhere on sidebar or overlay (swipe left to close)
    const shouldStartSwipe = isSidebarOpen
      ? target.closest('.sidebar') || target.closest('.sidebar-overlay')
      : startX < EDGE_ZONE;

    if (shouldStartSwipe) {
      sidebarSwipeStartX = startX;
      sidebarSwipeCurrentX = startX;
      isSidebarSwiping = false;
      activeSwipeType = 'sidebar';
    } else {
      // Reset if we're not starting a sidebar swipe
      if (activeSwipeType === 'sidebar') {
        activeSwipeType = 'none';
      }
    }
  };

  const handleSidebarTouchMove = (e: TouchEvent): void => {
    if (activeSwipeType !== 'sidebar') return;

    sidebarSwipeCurrentX = e.touches[0].clientX;
    const deltaX = sidebarSwipeCurrentX - sidebarSwipeStartX;
    const isSidebarOpen = sidebar.classList.contains('open');

    // Determine if this is a horizontal swipe
    if (!isSidebarSwiping && Math.abs(deltaX) > 10) {
      isSidebarSwiping = true;
    }

    if (isSidebarSwiping) {
      let translateX: number;

      if (isSidebarOpen) {
        // Sidebar is open - allow swiping left to close
        translateX = Math.max(Math.min(deltaX, 0), -sidebarWidth);
      } else {
        // Sidebar is closed - allow swiping right to open
        translateX = Math.min(Math.max(deltaX - sidebarWidth, -sidebarWidth), 0);
      }

      sidebar.style.transform = `translateX(${translateX}px)`;
      sidebar.style.transition = 'none';
    }
  };

  const handleSidebarTouchEnd = (): void => {
    if (activeSwipeType !== 'sidebar') return;

    const deltaX = sidebarSwipeCurrentX - sidebarSwipeStartX;
    const isSidebarOpen = sidebar.classList.contains('open');

    sidebar.style.transform = '';
    sidebar.style.transition = '';

    if (isSidebarSwiping) {
      if (isSidebarOpen && deltaX < -SWIPE_THRESHOLD) {
        // Close sidebar
        closeSidebar();
      } else if (!isSidebarOpen && deltaX > SWIPE_THRESHOLD) {
        // Open sidebar
        toggleSidebar();
      }
    }

    isSidebarSwiping = false;
    activeSwipeType = 'none';
  };

  // Handle touch cancel (iOS Safari can cancel touches during gestures)
  const handleSidebarTouchCancel = (): void => {
    sidebar.style.transform = '';
    sidebar.style.transition = '';
    isSidebarSwiping = false;
    activeSwipeType = 'none';
  };

  // Attach sidebar swipe to main area (for edge swipe to open)
  main.addEventListener('touchstart', handleSidebarTouchStart, { passive: true });
  main.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  main.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });
  main.addEventListener('touchcancel', handleSidebarTouchCancel, { passive: true });

  // Attach to sidebar itself (for swipe left to close)
  sidebar.addEventListener('touchstart', handleSidebarTouchStart, { passive: true });
  sidebar.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  sidebar.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });
  sidebar.addEventListener('touchcancel', handleSidebarTouchCancel, { passive: true });

  // Listen on document for overlay swipes and edge swipes
  document.addEventListener('touchstart', (e) => {
    const target = e.target as HTMLElement;
    const startX = e.touches[0].clientX;
    // Handle overlay swipes or edge swipes outside sidebar
    if (target.closest('.sidebar-overlay') || (startX < EDGE_ZONE && !target.closest('.sidebar'))) {
      handleSidebarTouchStart(e);
    }
  }, { passive: true });

  document.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  document.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });
  document.addEventListener('touchcancel', handleSidebarTouchCancel, { passive: true });

  // Close swipe on outside touch
  document.addEventListener('touchstart', (e) => {
    if (!(e.target as HTMLElement).closest('.conversation-item-wrapper')) {
      resetSwipeStates();
    }
  }, { passive: true });
}
