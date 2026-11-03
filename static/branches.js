(() => {
    const picker = document.getElementById('branch-picker');
    if (!picker) return;
    const search = document.getElementById('search-branches');
    const more = document.getElementById('more-branches');
    const message = document.getElementById('branch-message');
    const list = document.getElementById('branch-list');
    const tokens = [...document.querySelectorAll('.selection-token')];
    const submits = [...document.querySelectorAll('.branch-submit')];
    let page = 1, busy = false, controller = null, expiry = null, generation = 0;
    const seen = new Set();

    function clearSelection() {
        tokens.forEach(input => { input.value = ''; });
        submits.forEach(button => { button.disabled = true; });
        list.querySelectorAll('input').forEach(input => { input.checked = false; });
        clearTimeout(expiry);
    }
    function invalidate() {
        generation++;
        controller?.abort();
        clearSelection();
        list.replaceChildren();
        seen.clear();
        page = 1;
        more.hidden = true;
        message.textContent = '최신 정보 확인을 위해 주변 지점을 다시 검색해 주세요.';
    }
    async function load(reset) {
        if (busy) return;
        if (reset) { clearSelection(); list.replaceChildren(); seen.clear(); page = 1; }
        busy = true; search.disabled = true; more.disabled = true;
        message.textContent = '회원 배달 주소 주변 지점 검색 중...';
        controller = new AbortController();
        const currentGeneration = generation;
        const timeout = setTimeout(() => controller?.abort(), 30000);
        try {
            const response = await fetch(`${picker.dataset.url}?page=${page}`, {signal: controller.signal, cache: 'no-store'});
            const data = await response.json();
            if (currentGeneration !== generation) return;
            if (!response.ok) throw new Error(data.message || '지점을 검색할 수 없습니다.');
            for (const place of data.places) {
                if (seen.has(place.place_id)) continue;
                seen.add(place.place_id);
                const label = document.createElement('label');
                label.style.display = 'block'; label.style.padding = '12px';
                const radio = document.createElement('input');
                const selectionExpires = Date.now() + 10*60*1000;
                radio.type = 'radio'; radio.name = 'location-choice';
                radio.addEventListener('change', () => {
                    if (Date.now() >= selectionExpires) {
                        clearSelection();
                        message.textContent = '검색 정보가 만료되었습니다. 지점을 다시 검색해 주세요.';
                        return;
                    }
                    clearTimeout(expiry);
                    tokens.forEach(input => { input.value = place.selection_token; });
                    submits.forEach(button => { button.disabled = false; });
                    message.textContent = `선택한 실제 위치: ${place.display_name || '가상 음식점 지점'}. 메뉴는 가상 음식점 데이터입니다.`;
                    // Expire before the server's 15-minute selection token expires.
                    expiry = setTimeout(() => { clearSelection(); message.textContent = '선택이 만료되었습니다. 다시 검색해 주세요.'; }, selectionExpires-Date.now());
                });
                label.append(radio, document.createTextNode(`위치 안내: ${place.display_name || '가상 음식점 지점'} / ${place.road_address || place.lot_address} / 직선거리 약 ${place.nearby_distance.toLocaleString()}m (도로거리 확인 전)`));
                list.append(label);
            }
            more.hidden = data.is_end;
            page++;
            message.textContent = seen.size ? '위치를 선택한 후 가상 메뉴를 담아 주세요. 실제 도로거리는 장바구니에서 검사합니다.' : '이 검색 페이지에는 검증된 주변 지점이 없습니다.';
        } catch (error) {
            if (currentGeneration !== generation) return;
            clearSelection();
            message.textContent = error.name === 'AbortError' ? '검색이 취소되거나 시간이 초과되었습니다. 다시 시도해 주세요.' : error.message;
            // Keep the same page for retry. No nationwide or fixed-address fallback.
        } finally {
            clearTimeout(timeout); busy = false; controller = null;
            search.disabled = false; more.disabled = false;
        }
    }
    search.addEventListener('click', () => load(true));
    more.addEventListener('click', () => load(false));
    document.querySelectorAll('.branch-cart-form').forEach(form => form.addEventListener('submit', event => {
        if (busy || !form.querySelector('.selection-token').value) { event.preventDefault(); return; }
        submits.forEach(button => { button.disabled = true; });
    }));
    window.addEventListener('pagehide', invalidate);
    window.addEventListener('pageshow', invalidate);
    window.addEventListener('focus', () => { if (!busy) invalidate(); });
})();
