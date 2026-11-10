const savingControls = document.querySelector('.saving-periods');
if (savingControls) {
    const buttons = [...savingControls.querySelectorAll('button')];
    const panels = buttons.map(button => document.getElementById(button.getAttribute('aria-controls')));

    function selectPeriod(selected) {
        buttons.forEach((button, index) => {
            button.setAttribute('aria-pressed', String(index === selected));
            panels[index].hidden = index !== selected;
        });
    }

    buttons.forEach((button, index) => button.addEventListener('click', () => selectPeriod(index)));
    selectPeriod(0);
    savingControls.hidden = false;
}
