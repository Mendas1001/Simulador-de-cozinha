"""
main.py - ponto de entrada (terminal)

Uso (na pasta do projeto):
    python main.py                      # carga padrão, FCFS depois SJF
    python main.py --simultaneo         # roda os dois algoritmos ao mesmo tempo
    python main.py --escala 0.1         # mais rápido (1 unidade = 0.1 s)
    python main.py --aleatorio 10 --seed 42
    python main.py --cozinheiros 3
"""

import argparse

from cozinha.relatorio import ImpressoraConsole, relatorio_comparativo
from cozinha.simulador import carga_aleatoria, carga_padrao, comparar


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulador de cozinha: FCFS x SJF")
    ap.add_argument("--cozinheiros", type=int, default=2, help="número de cozinheiros (padrão 2)")
    ap.add_argument("--escala", type=float, default=0.25, help="segundos reais por unidade de tempo")
    ap.add_argument("--simultaneo", action="store_true", help="roda FCFS e SJF em paralelo")
    ap.add_argument("--aleatorio", type=int, metavar="N", help="gera N pedidos aleatórios")
    ap.add_argument("--seed", type=int, help="semente da carga aleatória")
    args = ap.parse_args()

    pedidos = carga_aleatoria(args.aleatorio, args.seed) if args.aleatorio else carga_padrao()

    print("Carga inicial (igual para os dois algoritmos):")
    for p in pedidos:
        print(f"  Pedido {p.id}: chegada={p.chegada}  preparo={p.burst}")
    print()

    resultados = comparar(pedidos, num_cozinheiros=args.cozinheiros, escala=args.escala,
                          simultaneo=args.simultaneo, ouvintes=[ImpressoraConsole()])

    print(relatorio_comparativo(resultados))


if __name__ == "__main__":
    main()
