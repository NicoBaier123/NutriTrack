import matplotlib.pyplot as plt

metrics = ['Hit Rate', 'Precision@3', 'Nutr. Compliance', 'Latency (norm)', 'Macro Compliance']
ist = [36.67, 26.67, 80, 100 - (2.08/0.3)*10, 100]  # Latency normalisiert
ziel = [70, 80, 95, 100, 100]

x = range(len(metrics))
plt.bar([i-0.2 for i in x], ist, width=0.4, label='Ist-Wert', color='red', alpha=0.7)
plt.bar([i+0.2 for i in x], ziel, width=0.4, label='Ziel-Wert', color='green', alpha=0.7)
plt.xticks(x, metrics, rotation=45, ha='right')
plt.ylabel('Wert (%)')
plt.legend()
plt.title('KPIs: Ist vs. Ziel')
plt.tight_layout()
plt.savefig('metrics_comparison.png', dpi=300)