// WasseLead — browser demo.
// A faithful re-implementation of src/wasselead.py's ranking logic so the demo
// is genuinely interactive, not a mock-up. Kept intentionally small: urgency,
// dedupe, opt-out and the reply windows are the parts a buyer would poke at.
const WINDOW = { hot: 2, warm: 24, cold: 48 };
const HOURS = 3600e3;

export function normPhone(raw){
  let d = String(raw).replace(/\D/g,'');
  if(!d) throw new Error("no digits found in phone '"+raw+"'");
  if(d.startsWith('0091')) d = d.slice(4);
  else if(d.startsWith('91') && d.length===12) d = d.slice(2);
  if(d.startsWith('0') && d.length===11) d = d.slice(1);
  if(d.length===10) return '91'+d;
  if(d>=11 && d<=15) return d;
  throw new Error("phone '"+raw+"' does not look like a real number");
}

export function urgency(l){
  if(l.optedOut) return 'do_not_disturb';
  if(l.booked) return 'cold';
  if(l.replied) return 'hot';
  const t = l.message.toLowerCase();
  if(l.message.includes('?') || ['price','cost','charges','rate','how much','available','timing'].some(w=>t.includes(w))) return 'hot';
  if(['interested','sure','ok','yes','tell me more','details'].some(w=>t.includes(w))) return 'warm';
  return 'cold';
}

function first(n){ return (n.trim().split(/\s+/)[0]) || 'there'; }

// Normalise an owner's slot text to exactly one trailing full stop, so the
// composed message is never a run-on or a double stop. Mirrors clean() in
// src/wasselead.py.
export function clean(s){
  const v = String(s).trim().replace(/\.+$/,'');
  return v ? v + '.' : v;
}

const TEMPLATES = {
  hot:  c => `Hi ${first(c.name)}, got your enquiry about ${clean(c.interest)}. Is this week okay for a quick call?`,
  warm: c => `Hi ${first(c.name)}, thanks for reaching out about ${clean(c.interest)}. Shall I share timings?`,
  cold: c => `Hi ${first(c.name)}, this is about ${clean(c.interest)} you asked about. Want me to send the details?`
};

export function compose(c, level){
  const lead = c.lead;
  const text = TEMPLATES[level](c);
  return {
    level,
    phone: lead.phone,
    name: lead.name,
    message: text,
    reply_by: new Date(lead.due_at).toISOString()
  };
}

export function buildQueue(leads, config){
  const seen = new Set();
  const kept = [];
  const skipped = [];
  for(const lead of leads){
    if(!lead.phone || !String(lead.phone).trim()){
      skipped.push({ name: lead.name || '(no name)', reason: 'missing phone' });
      continue;
    }
    let p;
    try { p = normPhone(lead.phone); }
    catch(e){ skipped.push({ name: lead.name || '(no name)', reason: e.message }); continue; }
    if(seen.has(p)){ skipped.push({ name: lead.name, reason: 'duplicate number' }); continue; }
    seen.add(p);
    const level = urgency(lead);
    if(level === 'do_not_disturb'){ skipped.push({ name: lead.name, reason: 'opted out' }); continue; }
    kept.push({ ...lead, phone: p, urgency: level });
  }
  for(const k of kept) k.due_at = (new Date(k.due_at)).toISOString();
  kept.sort((a,b) => new Date(a.due_at) - new Date(b.due_at));
  kept.sort((a,b) => (WINDOW[a.urgency] - WINDOW[b.urgency]) || 0);
  return { queue: kept, skipped: skipped };
}

export const SAMPLE = [
  { name:'Priya',   phone:'98765 43210', message:'What are the charges for a cleaning?', optedOut:false, booked:false, replied:false },
  { name:'Rahul',   phone:'+91 98765 00001', message:'Interested, tell me more',      optedOut:false, booked:false, replied:false },
  { name:'Aman',    phone:'98765 11111',     message:'Do you have slots tomorrow?',   optedOut:false, booked:false, replied:false },
  { name:'Neha',    message:'Do you offer home service?', optedOut:false, booked:false, replied:false },
  { name:'Vikram',  phone:'098765 11111',    message:'ok',                          optedOut:false, booked:false, replied:false },
  { name:'Sana',    phone:'98765 22222',     message:'Please remove me from this list', optedOut:true, booked:false, replied:false }
];

export function dueAt(level, now){
  const h = WINDOW[level];
  if(level === 'hot') return new Date(now + 2*HOURS).toISOString();
  if(level === 'warm') return new Date(now + 24*HOURS).toISOString();
  return new Date(now + 48*HOURS).toISOString();
}