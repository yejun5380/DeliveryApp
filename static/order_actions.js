/* The server supplies remaining time from the persisted order snapshot. */
(() => {
    const links = [...document.querySelectorAll('[data-delivery-remaining]')];
    const forms = [...document.querySelectorAll('[data-cancel-remaining]')];
    const started = performance.getEntriesByType('navigation')[0]?.responseStart || performance.now();
    const timers = [];
    function stop() { timers.splice(0).forEach(clearTimeout); }
    function update() {
        stop();
        links.forEach(link => {
            const remaining = Number(link.dataset.deliveryRemaining) * 1000 - (performance.now() - started);
            if (!Number.isFinite(remaining) || remaining <= 0) link.hidden = true;
            else timers.push(setTimeout(() => { link.hidden = true; }, remaining));
        });
        forms.forEach(form => {
            const remaining = Number(form.dataset.cancelRemaining) * 1000 - (performance.now() - started);
            const expire = () => {
                const button = form.querySelector('button');
                button.disabled = true;
                button.textContent = '취소 마감';
                button.title = '주문 접수 단계가 끝나 취소할 수 없습니다.';
                const badge = form.closest?.('.order-card, .order-overview')?.querySelector('.order-badge');
                if (badge?.textContent.trim() === '주문 접수') badge.textContent = '준비 중';
            };
            if (!Number.isFinite(remaining) || remaining <= 0) expire();
            else timers.push(setTimeout(expire, remaining));
        });
    }
    forms.forEach(form => form.addEventListener('submit', event => {
        const remaining = Number(form.dataset.cancelRemaining) * 1000 - (performance.now() - started);
        if (!Number.isFinite(remaining) || remaining <= 0) { event.preventDefault(); update(); }
    }));
    window.addEventListener('pagehide', stop);
    window.addEventListener('pageshow', update);
    update();
})();
