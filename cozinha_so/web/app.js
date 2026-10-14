/* ==========================================================
   Cozinha SO - frontend (JavaScript puro, sem bibliotecas)

   Fluxo:
     1. Botão "Iniciar" -> POST /api/iniciar
     2. Abrimos um EventSource em /api/stream (Server-Sent Events)
     3. Cada evento do backend chega aqui como JSON:
          config | chegada | inicio | fim | ocioso | fim_geral | erro
        e atualiza só o pedaço da tela que mudou.
     4. Um laço requestAnimationFrame anima o que depende do tempo
        (barras de progresso, relógio, Gantt crescendo).
   ========================================================== */
"use strict";

// ---------------------------------------------------------------- constantes
const ALGS = {
  FCFS: { titulo: "FCFS", desc: "First-Come, First-Served: atende por ordem de chegada." },
  SJF:  { titulo: "SJF",  desc: "Shortest Job First (não-preemptivo): o pedido mais rápido primeiro." },
};
const PRATOS = ["🍕", "🍔", "🍝", "🍣", "🥗", "🌮", "🍜", "🥘", "🍛", "🍤", "🥪", "🍲"];

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const emojiDe = (id) => PRATOS[(id - 1) % PRATOS.length];
const matiz = (id) => (id * 47) % 360;                       // cor própria de cada pedido
// 2 casas, arredondando "meio para cima" (3.125 -> "3,13"), igual ao relatório do terminal
const fmt = (n) => (Math.round((n + 1e-9) * 100) / 100).toFixed(2).replace(".", ",");

// ---------------------------------------------------------------- estado
let cfg = null;               // evento "config" da simulação atual
let paineis = [];             // um objeto por algoritmo
let porAlg = new Map();       // "FCFS" -> painel
let es = null;                // EventSource
let encerrado = false;        // true depois de fim_geral (evita reconexão)

// ---------------------------------------------------------------- controles
const btn = $("#btn-iniciar");

$("#carga").addEventListener("change", () => {
  const aleatoria = $("#carga").value === "aleatoria";
  $("#lbl-n").hidden = !aleatoria;
  $("#lbl-seed").hidden = !aleatoria;
});
btn.addEventListener("click", iniciar);

function definirStatus(texto, classe = "") {
  const el = $("#status");
  el.textContent = texto;
  el.className = "status " + classe;
}

async function iniciar() {
  btn.disabled = true;
  definirStatus("Iniciando…", "rodando");
  const corpo = {
    cozinheiros: Number($("#cozinheiros").value),
    escala: Number($("#escala").value),
    carga: $("#carga").value,
    n: Number($("#n").value),
    seed: $("#seed").value.trim(),
  };
  try {
    const r = await fetch("/api/iniciar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
    const j = await r.json();
    if (!r.ok) {
      definirStatus(j.erro || "Erro ao iniciar", "erro");
      btn.disabled = false;
      return;
    }
    abrirStream();
  } catch (e) {
    definirStatus("Servidor indisponível", "erro");
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- SSE
function abrirStream() {
  if (es) es.close();
  encerrado = false;
  es = new EventSource("/api/stream");
  es.onmessage = (e) => tratar(JSON.parse(e.data));
  es.onerror = () => {
    if (!encerrado) definirStatus("Conexão perdida… reconectando", "erro");
  };
}

function tratar(ev) {
  switch (ev.tipo) {
    case "config":
      montarPaineis(ev);
      definirStatus(ev.seed != null ? `Em execução… (seed ${ev.seed})` : "Em execução…", "rodando");
      btn.disabled = true;
      break;
    case "chegada":
    case "inicio":
    case "fim":
    case "ocioso": {
      const p = porAlg.get(ev.algoritmo);
      if (p) aplicar(p, ev);
      break;
    }
    case "fim_geral":
      mostrarComparativo(ev.resultados);
      finalizar("Concluída ✓", "ok");
      break;
    case "erro":
      finalizar("Erro: " + ev.mensagem, "erro");
      break;
  }
}

function finalizar(texto, classe) {
  encerrado = true;
  if (es) es.close();
  definirStatus(texto, classe);
  btn.disabled = false;
}

// ---------------------------------------------------------------- montagem da tela
function montarPaineis(c) {
  cfg = c;
  paineis = [];
  porAlg = new Map();
  $("#vazio").hidden = true;
  $("#comparativo").hidden = true;
  $("#comparativo").innerHTML = "";

  const raiz = $("#paineis");
  raiz.innerHTML = "";
  const tpl = $("#tpl-painel");

  for (const alg of c.algoritmos) {
    const el = tpl.content.firstElementChild.cloneNode(true);
    el.dataset.alg = alg;
    $(".alg-titulo", el).textContent = ALGS[alg].titulo;
    $(".alg-desc", el).textContent = ALGS[alg].desc;
    raiz.appendChild(el);

    const q = (nome) => el.querySelector(`[data-el="${nome}"]`);
    const p = {
      alg, el, q,
      pedidos: new Map(),     // id -> estado do pedido neste algoritmo
      cooks: new Map(),       // nome -> estação
      chips: new Map(),       // id -> chip na esteira
      trilhas: new Map(),     // nome -> trilha do Gantt
      total: c.pedidos.length,
      faltam: c.pedidos.length, naFila: 0, concluidos: 0,
      iniciados: 0, somaEspera: 0,
      fimTempo: null, eixoT: null,
    };

    // cada algoritmo tem sua PRÓPRIA cópia do estado dos pedidos
    for (const d of c.pedidos) {
      p.pedidos.set(d.id, {
        id: d.id, chegada: d.chegada, burst: d.burst,
        estado: "futuro",       // futuro -> fila -> preparando -> pronto
        inicio: null, fim: null, cozinheiro: null, bloco: null,
      });
    }

    // --- estações dos cozinheiros
    for (const nome of c.cozinheiros) {
      const est = document.createElement("div");
      est.className = "estacao";
      est.innerHTML = `
        <div class="chef">👨‍🍳</div>
        <div class="est-info">
          <strong>${nome}</strong>
          <span class="est-status">Ocioso</span>
          <div class="prato">
            <span class="emoji">🍽️</span>
            <div class="barra"><i></i></div>
            <small class="prog">—</small>
          </div>
        </div>`;
      p.q("estacoes").appendChild(est);
      p.cooks.set(nome, {
        nome, el: est, status: "ocioso", pedido: null, ultimo: null, flash: false,
        statusEl: $(".est-status", est), barra: $(".barra i", est),
        prog: $(".prog", est), emoji: $(".prato .emoji", est),
      });
    }

    // --- Gantt (um trilho por cozinheiro)
    const g = p.q("gantt");
    g.innerHTML = `
      <div class="g-corpo">
        <div class="g-nomes">${c.cozinheiros.map((_, i) => `<span>C${i + 1}</span>`).join("")}</div>
        <div class="g-area">
          <div class="g-trilhas"></div>
          <div class="g-cursor"></div>
          <div class="g-eixo"></div>
        </div>
      </div>`;
    c.cozinheiros.forEach((nome) => {
      const t = document.createElement("div");
      t.className = "g-trilha";
      $(".g-trilhas", g).appendChild(t);
      p.trilhas.set(nome, t);
    });
    p.cursor = $(".g-cursor", g);
    p.eixoEl = $(".g-eixo", g);

    paineis.push(p);
    porAlg.set(alg, p);
    atualizarPainel(p);
  }
}

// ---------------------------------------------------------------- aplicar eventos
function aplicar(p, ev) {
  const ped = ev.pedido_id != null ? p.pedidos.get(ev.pedido_id) : null;

  switch (ev.tipo) {
    case "chegada":
      // Só entra na fila se ainda não foi pego (eventos de threads diferentes
      // podem chegar fora de ordem por alguns milissegundos).
      if (ped.estado === "futuro") {
        ped.estado = "fila";
        p.faltam--; p.naFila++;
        const chip = criarChip(ped);
        p.chips.set(ped.id, chip);
        p.q("esteira").appendChild(chip);
        log(p, ev.tempo, `Pedido ${ped.id} chegou na esteira (preparo: ${ped.burst}u)`);
      }
      break;

    case "inicio": {
      const cook = p.cooks.get(ev.cozinheiro);
      if (ped.estado === "futuro") p.faltam--;
      else if (ped.estado === "fila") p.naFila--;
      const chip = p.chips.get(ped.id);
      if (chip) { chip.remove(); p.chips.delete(ped.id); }

      ped.estado = "preparando";
      ped.inicio = ev.tempo;
      ped.cozinheiro = ev.cozinheiro;
      p.iniciados++;
      p.somaEspera += ev.tempo - ped.chegada;

      cook.status = "preparando";
      cook.pedido = ped;
      cook.flash = false;
      atualizarEstacao(cook);
      criarBlocoGantt(p, ped);
      log(p, ev.tempo, `${ev.cozinheiro} ${p.alg} pegou o Pedido ${ped.id} (preparo: ${ped.burst}u)`);
      break;
    }

    case "fim": {
      const cook = p.cooks.get(ev.cozinheiro);
      ped.estado = "pronto";
      ped.fim = ev.tempo;
      p.concluidos++;

      cook.status = "ocioso";
      cook.pedido = null;
      cook.ultimo = ped.id;
      cook.flash = true;                       // mostra "Concluiu o Pedido X" por um instante
      atualizarEstacao(cook);
      setTimeout(() => { cook.flash = false; atualizarEstacao(cook); }, 1400);

      p.q("entrega").appendChild(criarChip(ped, true));
      log(p, ev.tempo, `${ev.cozinheiro} terminou o Pedido ${ped.id}`);
      break;
    }

    case "ocioso": {
      const cook = p.cooks.get(ev.cozinheiro);
      cook.status = "encerrado";
      atualizarEstacao(cook);
      log(p, ev.tempo, `${ev.cozinheiro} encerrou (sem mais pedidos)`);
      // Todos encerraram? Congela o relógio deste painel no fim do último pedido.
      if ([...p.cooks.values()].every((c) => c.status === "encerrado")) {
        p.fimTempo = Math.max(...[...p.pedidos.values()].map((d) => d.fim ?? 0));
        const selo = p.q("selo");
        selo.textContent = "finalizado";
        selo.classList.add("fim");
      }
      break;
    }
  }
  atualizarPainel(p);
}

// ---------------------------------------------------------------- pedaços da tela
function criarChip(ped, entregue = false) {
  const el = document.createElement("div");
  el.className = "chip" + (entregue ? " entregue" : "");
  el.style.setProperty("--h", matiz(ped.id));
  const detalhe = entregue
    ? `espera ${ped.inicio - ped.chegada}u`
    : `${ped.burst}u`;
  el.title = `Pedido ${ped.id} · chegada ${ped.chegada} · preparo ${ped.burst}u`;
  el.innerHTML = `<span class="emoji">${emojiDe(ped.id)}</span><b>P${ped.id}</b><small>${detalhe}</small>`;
  return el;
}

function atualizarEstacao(cook) {
  const el = cook.el;
  el.classList.toggle("preparando", cook.status === "preparando");
  el.classList.toggle("encerrado", cook.status === "encerrado");
  el.classList.toggle("pronto-flash", cook.flash);

  let texto;
  if (cook.status === "preparando") texto = `Preparando o Pedido ${cook.pedido.id}`;
  else if (cook.status === "encerrado") texto = "Encerrou o expediente";
  else texto = cook.flash ? `✓ Concluiu o Pedido ${cook.ultimo}` : "Ocioso";
  cook.statusEl.textContent = texto;

  cook.emoji.textContent = cook.status === "preparando" ? emojiDe(cook.pedido.id) : "🍽️";
  if (cook.status !== "preparando") {
    cook.barra.style.width = "0%";
    cook.prog.textContent = "—";
  }
}

function criarBlocoGantt(p, ped) {
  const b = document.createElement("div");
  b.className = "g-bloco";
  b.style.setProperty("--h", matiz(ped.id));
  b.textContent = "P" + ped.id;
  b.title = `Pedido ${ped.id} · ${ped.cozinheiro} · início ${ped.inicio}`;
  p.trilhas.get(ped.cozinheiro).appendChild(b);
  ped.bloco = b;                    // posição/largura são ajustadas em cada frame
}

function atualizarPainel(p) {
  p.q("m-conc").textContent = `${p.concluidos}/${p.total}`;
  p.q("m-fila").textContent = p.naFila;
  p.q("m-tme").textContent = p.iniciados ? fmt(p.somaEspera / p.iniciados) : "—";
  p.q("faltam").textContent = p.faltam > 0 ? `· ${p.faltam} ainda a chegar` : "";
  vazioMsg(p.q("esteira"), "Nenhum pedido aguardando");
  vazioMsg(p.q("entrega"), "Nenhuma entrega ainda");
}

// Mostra uma mensagem discreta quando o contêiner não tem nenhum chip.
function vazioMsg(contenedor, msg) {
  const tem = contenedor.querySelector(".chip");
  const aviso = contenedor.querySelector(".vazio-msg");
  if (!tem && !aviso) {
    const s = document.createElement("span");
    s.className = "vazio-msg";
    s.textContent = msg;
    contenedor.appendChild(s);
  } else if (tem && aviso) {
    aviso.remove();
  }
}

function log(p, tempo, texto) {
  const box = p.q("log");
  const linha = document.createElement("div");
  linha.innerHTML = `<b>t=${tempo}</b> ${texto}`;
  box.appendChild(linha);
  while (box.children.length > 80) box.firstChild.remove();
  box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- animação (rAF)
// Eixo de tempo do Gantt: o MESMO nos dois painéis, para ficarem comparáveis.
function calcularT(agora) {
  if (paineis.every((p) => p.fimTempo != null)) {
    return Math.max(1, ...paineis.map((p) => p.fimTempo));
  }
  const nCook = cfg.cozinheiros.length;
  const soma = cfg.pedidos.reduce((s, d) => s + d.burst, 0);
  const base = Math.ceil(soma / nCook) + 2;
  const maisAdiantado = Math.max(...paineis.map((p) => p.fimTempo ?? agora));
  return Math.max(base, Math.ceil(maisAdiantado) + 2);
}

function desenharEixo(p, T) {
  const passo = Math.max(1, Math.ceil(T / 22));
  let html = "";
  for (let t = 0; t <= T; t += passo) html += `<span style="left:${(t / T) * 100}%">${t}</span>`;
  p.eixoEl.innerHTML = html;
  p.eixoT = T;
}

function quadro() {
  if (cfg && paineis.length) {
    // relógio comum: tempo real desde o início -> unidades da simulação
    const agora = Math.max(0, (Date.now() - cfg.inicio_epoch_ms) / (cfg.escala * 1000));
    const T = calcularT(agora);

    for (const p of paineis) {
      const t = p.fimTempo ?? agora;
      p.q("relogio").textContent = t.toFixed(1);

      // barras de progresso dos cozinheiros
      for (const cook of p.cooks.values()) {
        if (!cook.pedido) continue;
        const d = cook.pedido;
        const feito = Math.max(0, t - d.inicio);
        cook.barra.style.width = Math.min(100, (feito / d.burst) * 100) + "%";
        cook.prog.textContent = `${Math.min(d.burst, Math.floor(feito))}/${d.burst}u`;
      }

      // blocos do Gantt (os em andamento crescem em tempo real)
      for (const d of p.pedidos.values()) {
        if (!d.bloco) continue;
        const fimVisivel = d.fim ?? Math.min(t, d.inicio + d.burst);
        d.bloco.style.left = (d.inicio / T) * 100 + "%";
        d.bloco.style.width = (Math.max(0, fimVisivel - d.inicio) / T) * 100 + "%";
      }

      // cursor "agora" e eixo
      p.cursor.style.display = p.fimTempo != null ? "none" : "block";
      p.cursor.style.left = (Math.min(t, T) / T) * 100 + "%";
      if (p.eixoT !== T) desenharEixo(p, T);
    }
  }
  requestAnimationFrame(quadro);
}

// ---------------------------------------------------------------- comparativo final
function mostrarComparativo(resultados) {
  const algs = cfg.algoritmos;
  const dados = {};
  for (const alg of algs) {
    const r = resultados[alg];
    let pior = { valor: -1, id: null };
    for (const d of r.pedidos) if (d.espera > pior.valor) pior = { valor: d.espera, id: d.id };
    dados[alg] = { r, tme: r.tme, tmt: r.tmt, dur: r.duracao, pior };
  }

  const [a, b] = algs;
  const empate = Math.abs(dados[a].tme - dados[b].tme) < 1e-9;
  const venc = empate ? null : (dados[a].tme < dados[b].tme ? a : b);
  const perd = venc === a ? b : a;
  const maxTme = Math.max(dados[a].tme, dados[b].tme);

  // --- veredito em texto
  let veredito;
  if (empate) {
    veredito = `Empate no Tempo Médio de Espera: ${fmt(dados[a].tme)}.`;
  } else {
    const pct = ((dados[perd].tme - dados[venc].tme) / dados[perd].tme) * 100;
    veredito = `<strong>${venc}</strong> teve o menor TME: ${fmt(dados[venc].tme)} contra ${fmt(dados[perd].tme)} ` +
               `(${pct.toFixed(1).replace(".", ",")}% menor).`;
  }
  veredito += ` Pedido que mais esperou: ` +
    algs.map((x) => `${x} → P${dados[x].pior.id} (${dados[x].pior.valor}u)`).join(" · ") + ".";
  if (dados.SJF && dados.FCFS && dados.SJF.pior.valor > dados.FCFS.pior.valor) {
    veredito += " O SJF reduz a média, mas pedidos longos podem esperar mais (risco de starvation).";
  }

  // --- cartões grandes
  const cartoes = algs.map((alg) => `
    <div class="comp-card ${alg.toLowerCase()} ${alg === venc ? "vencedor" : ""}">
      ${alg === venc ? '<span class="coroa">🏆 menor TME</span>' : ""}
      <h3>${alg}</h3>
      <div class="grande">${fmt(dados[alg].tme)}</div>
      <div class="rot">Tempo Médio de Espera (TME)</div>
      <div class="barra-tme"><i style="width:0%" data-alvo="${(dados[alg].tme / maxTme) * 100}"></i></div>
    </div>`).join("");

  // --- tabela de métricas (destaca o menor valor de cada linha)
  const linha = (rotulo, chave, formatar) => {
    const va = dados[a][chave], vb = dados[b][chave];
    const cel = (v, outro) => `<td class="num ${v < outro ? "melhor" : ""}">${formatar(v)}</td>`;
    return `<tr><td>${rotulo}</td>${cel(va, vb)}${cel(vb, va)}</tr>`;
  };
  const tabela = `
    <table class="tab">
      <thead><tr><th>Métrica</th><th class="num">${a}</th><th class="num">${b}</th></tr></thead>
      <tbody>
        ${linha("Tempo Médio de Espera (TME)", "tme", fmt)}
        ${linha("Tempo Médio de Turnaround (TMT)", "tmt", fmt)}
        <tr><td>Maior espera de um pedido</td>
            <td class="num">${dados[a].pior.valor}u (P${dados[a].pior.id})</td>
            <td class="num">${dados[b].pior.valor}u (P${dados[b].pior.id})</td></tr>
        ${linha("Duração total (makespan)", "dur", (v) => v + "u")}
      </tbody>
    </table>`;

  // --- espera de cada pedido nos dois algoritmos
  const esperaDe = (alg, id) => dados[alg].r.pedidos.find((d) => d.id === id).espera;
  const maxEspera = Math.max(1, dados[a].pior.valor, dados[b].pior.valor);
  const linhasPedidos = cfg.pedidos.map((d) => {
    const ea = esperaDe(a, d.id), eb = esperaDe(b, d.id);
    const barra = (cls, alg, v) =>
      `<div class="linha ${cls}"><i style="width:${Math.max(2, (v / maxEspera) * 130)}px"></i>${alg} ${v}u</div>`;
    return `<tr><td>${emojiDe(d.id)} P${d.id}</td><td class="num">${d.burst}u</td>
            <td><div class="dupla">${barra("f", a, ea)}${barra("s", b, eb)}</div></td></tr>`;
  }).join("");

  const raiz = $("#comparativo");
  raiz.innerHTML = `
    <h2>🏁 Comparativo final</h2>
    <p class="sub">Mesma carga de ${cfg.pedidos.length} pedidos e ${cfg.cozinheiros.length} cozinheiros em cada algoritmo.</p>
    <div class="comp-cards">${cartoes}</div>
    <div class="veredito">${veredito}</div>
    ${tabela}
    <h3 class="sec">Espera de cada pedido</h3>
    <table class="tab">
      <thead><tr><th>Pedido</th><th class="num">Preparo</th><th>Espera (${a} × ${b})</th></tr></thead>
      <tbody>${linhasPedidos}</tbody>
    </table>`;
  raiz.hidden = false;

  // anima as barras de TME (de 0 até o valor final)
  requestAnimationFrame(() => requestAnimationFrame(() => {
    raiz.querySelectorAll(".barra-tme i").forEach((i) => (i.style.width = i.dataset.alvo + "%"));
  }));
  raiz.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------- inicialização
requestAnimationFrame(quadro);

// Se a página foi recarregada no meio (ou depois) de uma simulação, reconecta:
// o servidor reenvia o histórico e a tela se reconstrói.
fetch("/api/estado")
  .then((r) => r.json())
  .then((s) => { if (s.existe) abrirStream(); })
  .catch(() => {});
