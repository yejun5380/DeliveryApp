const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const panels = [{}, {}, {}];
const caloriePanels=[{},{},{}];
const buttons = panels.map((_, index) => ({
    getAttribute: name => name === 'aria-controls' ? String(index) : null,
    setAttribute(name, value) { this[name] = value; },
    addEventListener(event, handler) { this[event] = handler; },
}));
const controls = {hidden: true, querySelectorAll: () => buttons};
const calorieButtons=caloriePanels.map((_,index)=>({
    getAttribute:()=>`calorie-${index}`,
    setAttribute(name,value){this[name]=value;},
    addEventListener(event,handler){this[event]=handler;},
}));
const calorieControls={hidden:true,querySelectorAll:()=>calorieButtons};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/saving.js'), 'utf8'), {
    document: {querySelectorAll: () => [controls,calorieControls], getElementById: id => id.startsWith('calorie-')?caloriePanels[Number(id.split('-')[1])]:panels[Number(id)]},
});

function assertSelected(index) {
    assert.deepEqual(buttons.map(button => button['aria-pressed']), panels.map((_, i) => String(i === index)));
    assert.deepEqual(panels.map(panel => panel.hidden), panels.map((_, i) => i !== index));
}

assert.equal(controls.hidden, false);
assertSelected(0);
for (const index of [1, 2, 0]) {
    buttons[index].click();
    assertSelected(index);
}
calorieButtons[2].click();
assert.deepEqual(caloriePanels.map(p=>p.hidden),[true,true,false]);
assertSelected(0);
buttons[1].click();
assert.deepEqual(caloriePanels.map(p=>p.hidden),[true,true,false]);
assertSelected(1);
