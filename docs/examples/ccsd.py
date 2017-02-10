"""Automatic derivation of CCSD equations.

"""

import os
import urllib.request

from pyspark import SparkConf, SparkContext
from sympy import IndexedBase, Rational

from drudge import PartHoleDrudge

n_cpus = os.cpu_count()
if 'SLURM_JOB_NUM_NODES' in os.environ:
    n_cpus *= int(os.environ['SLURM_JOB_NUM_NODES'])
n_parts = n_cpus

conf = SparkConf().setAppName('CCSD-derivation')
ctx = SparkContext(conf=conf)
dr = PartHoleDrudge(ctx)
p = dr.names

c_ = p.c_
c_dag = p.c_dag
a, b = p.V_dumms[:2]
i, j = p.O_dumms[:2]

t1 = IndexedBase('t1')
t2 = IndexedBase('t2')
dr.set_dbbar_base(t2, 2)

clusters = dr.einst(
    t1[a, i] * c_dag[a] * c_[i] +
    Rational(1, 4) * t2[a, b, i, j] * c_dag[a] * c_dag[b] * c_[j] * c_[i]
)

curr = dr.ham
h_bar = dr.ham
for order in range(0, 4):
    curr = (curr | clusters).simplify() * Rational(1, order + 1)
    curr.repartition(n_parts, cache=True)
    h_bar += curr
h_bar.repartition(n_parts, cache=True)

en_eqn = h_bar.eval_fermi_vev().simplify()

proj = c_dag[i] * c_[a]
t1_eqn = (proj * h_bar).eval_fermi_vev().simplify()

proj = c_dag[i] * c_dag[j] * c_[b] * c_[a]
t2_eqn = (proj * h_bar).eval_fermi_vev().simplify()

# Check with the result from TCE.
TCE_BASE_URL = 'http://www.scs.illinois.edu/~sohirata/'
tce_res = [
    dr.parse_tce(
        urllib.request.urlopen(TCE_BASE_URL + i).read().decode(),
        {1: t1, 2: t2}
    ).simplify()
    for i in ['ccsd_e.out', 'ccsd_t1.out', 'ccsd_t2.out']
    ]

print('Checking with TCE result: ')
print('Energy: ', en_eqn == tce_res[0])
print('T1 amplitude: ', t1_eqn == tce_res[1])
print('T2 amplitude: ', t2_eqn == tce_res[2])
