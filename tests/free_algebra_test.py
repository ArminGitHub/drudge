"""Tests for the basic tensor facilities using free algebra."""

import io
import os
import os.path
import pickle
import shutil

import pytest
from sympy import (
    sympify, IndexedBase, sin, cos, KroneckerDelta, symbols, conjugate, Wild,
    Rational
)

from drudge import Drudge, Range, Vec, Term, Perm, NEG, CONJ, TensorDef


@pytest.fixture(scope='module')
def free_alg(spark_ctx):
    """Initialize the environment for a free algebra."""

    dr = Drudge(spark_ctx)

    r = Range('R')
    dumms = sympify('i, j, k, l, m, n')
    dr.set_dumms(r, dumms)

    s = Range('S')
    s_dumms = symbols('alpha beta')
    dr.set_dumms(s, s_dumms)

    dr.add_resolver_for_dumms()

    v = Vec('v')
    dr.set_name(v)

    m = IndexedBase('m')
    dr.set_symm(m, Perm([1, 0], NEG))

    h = IndexedBase('h')
    dr.set_symm(h, Perm([1, 0], NEG | CONJ))

    dr.set_tensor_method('get_one', lambda x: 1)

    return dr


def test_drudge_has_names(free_alg):
    """Test the name archive for drudge objects.

    Here selected names are tested to makes sure all the code are covered.
    """

    p = free_alg.names

    # Range and dummy related.
    assert p.R == Range('R')
    assert len(p.R_dumms) == 6
    assert p.R_dumms[0] == p.i
    assert p.R_dumms[-1] == p.n

    # Vector bases.
    assert p.v == Vec('v')

    # Scalar bases.
    assert p.m == IndexedBase('m')


def test_tensor_can_be_created(free_alg):
    """Test simple tensor creation."""

    dr = free_alg
    p = dr.names
    i, v, r = p.i, p.v, p.R
    x = IndexedBase('x')

    # Create the tensor by two user creation functions.
    for tensor in [
        dr.sum((i, r), x[i] * v[i]),
        dr.einst(x[i] * v[i])
    ]:
        assert tensor.n_terms == 1

        terms = tensor.local_terms
        assert len(terms) == 1
        term = terms[0]
        assert term == Term(((i, r),), x[i], (v[i],))


def test_complex_tensor_creation(free_alg):
    """Test tensor creation involving operations."""

    dr = free_alg
    p = dr.names
    i, v, r = p.i, p.v, p.R
    x = IndexedBase('x')
    for summand in [(x[i] / 2) * v[i], x[i] * (v[i] / 2)]:
        tensor = dr.einst(summand)
        assert tensor.n_terms == 1

        terms = tensor.local_terms
        assert len(terms) == 1
        term = terms[0]
        assert term == Term(((i, r),), x[i] / 2, (v[i],))


def test_tensor_has_basic_operations(free_alg):
    """Test some of the basic operations on tensors.

    Tested in this module:

        1. Addition.
        2. Merge.
        3. Free variable.
        4. Dummy reset.
        5. Equality comparison.
        6. Expansion
        7. Mapping to scalars.
        8. Base presence testing.
    """

    dr = free_alg
    p = dr.names
    i, j, k, l, m = p.R_dumms[:5]
    x = IndexedBase('x')
    r = p.R
    v = p.v
    tensor = (
        dr.sum((l, r), x[i, l] * v[l]) +
        dr.sum((m, r), x[j, m] * v[m])
    )

    # Without dummy resetting, they cannot be merged.
    assert tensor.n_terms == 2
    assert tensor.merge().n_terms == 2

    # Free variables are important for dummy resetting.
    free_vars = tensor.free_vars
    assert free_vars == {x.label, i, j}

    # Reset dummy.
    reset = tensor.reset_dumms()
    expected = (
        dr.sum((k, r), x[i, k] * v[k]) +
        dr.sum((k, r), x[j, k] * v[k])
    )
    assert reset == expected
    assert reset.local_terms == expected.local_terms

    # Merge the terms.
    merged = reset.merge()
    assert merged.n_terms == 1
    term = merged.local_terms[0]
    assert term == Term(((k, r),), x[i, k] + x[j, k], (v[k],))

    # Slightly separate test for expansion.
    c, d = symbols('c d')
    tensor = dr.sum((i, r), x[i] * (c + d) * v[i])
    assert tensor.n_terms == 1
    expanded = tensor.expand()
    assert expanded.n_terms == 2

    # Here we also test concrete summation facility.
    expected = dr.sum(
        (i, r), (j, [c, d]), x[i] * j * v[i]
    )
    assert set(expected.local_terms) == set(expected.local_terms)

    # Test mapping to scalars.
    tensor = dr.sum((i, r), x[i] * v[i, j])
    y = IndexedBase('y')
    substs = {x: y, j: c}
    res = tensor.map2scalars(lambda x: x.xreplace(substs))
    assert res == dr.sum((i, r), y[i] * v[i, c])
    res = tensor.map2scalars(lambda x: x.xreplace(substs), skip_vecs=True)
    assert res == dr.sum((i, r), y[i] * v[i, j])

    # Test base presence.
    tensor = dr.einst(x[i] * v[i])
    assert tensor.has_base(x)
    assert tensor.has_base(v)
    assert not tensor.has_base(IndexedBase('y'))
    assert not tensor.has_base(Vec('w'))


def test_tensor_can_be_simplified_amp(free_alg):
    """Test the amplitude simplification for tensors.

    More than trivial tensor amplitude simplification is tested here.  Currently
    it mostly concentrates on the dispatching to SymPy and delta simplification.
    The master simplification is also tested.
    """

    dr = free_alg
    p = dr.names
    r = p.R
    s = p.S
    v = p.v
    i, j = p.R_dumms[:2]
    alpha = p.alpha

    x = IndexedBase('x')
    y = IndexedBase('y')
    theta = sympify('theta')

    tensor = (
        dr.sum((i, r), sin(theta) ** 2 * x[i] * v[i]) +
        dr.sum(
            (i, r), (j, r),
            cos(theta) ** 2 * x[j] * KroneckerDelta(i, j) * v[i]
        ) +
        dr.sum((i, r), (alpha, s), KroneckerDelta(i, alpha) * y[i] * v[i])
    )
    assert tensor.n_terms == 3

    first = tensor.simplify_deltas().simplify_amps()
    # Now we should have one term killed.
    assert first.n_terms == 2

    # Merge again should really simplify.
    merged = first.reset_dumms().merge().simplify_amps()
    assert merged.n_terms == 1
    expected = dr.sum((i, r), x[i] * v[i])
    assert merged == expected

    # The master simplification should do it in one turn.
    simpl = tensor.simplify()
    assert simpl == expected


def test_tensor_can_be_canonicalized(free_alg):
    """Test tensor canonicalization in simplification.

    The master simplification function is tested, the core simplification is at
    the canonicalization.  Equality testing with zero is also tested.
    """

    dr = free_alg
    p = dr.names
    i, j = p.R_dumms[:2]
    r = p.R
    m = p.m
    h = p.h
    v = p.v

    # Anti-symmetric real matrix.
    tensor = (
        dr.sum((i, r), (j, r), m[i, j] * v[i] * v[j]) +
        dr.sum((i, r), (j, r), m[j, i] * v[i] * v[j])
    )
    assert tensor.n_terms == 2

    res = tensor.simplify()
    assert res == 0

    # Hermitian matrix.
    tensor = dr.einst(
        h[i, j] * v[i] * v[j] + conjugate(h[j, i]) * v[i] * v[j]
    )
    assert tensor.n_terms == 2
    res = tensor.simplify()
    assert res == 0


def test_tensor_math_ops(free_alg):
    """Test tensor math operations.

    Mainly here we test addition, multiplication, and division.
    """

    dr = free_alg
    p = dr.names
    r = p.R
    v = p.v
    w = Vec('w')
    x = IndexedBase('x')
    i, j, k = p.R_dumms[:3]
    a = sympify('a')

    v1 = dr.sum((i, r), x[i] * v[i])
    w1 = dr.sum((i, r), x[i] * w[i])
    assert v1.n_terms == 1
    assert w1.n_terms == 1

    v1_neg = -v1
    assert v1_neg == dr.sum((i, r), -x[i] * v[i])

    v1_1 = v1 + 2
    assert v1_1.n_terms == 2
    assert v1_1 == 2 + v1

    w1_1 = w1 + a
    assert w1_1.n_terms == 2
    assert w1_1 == a + w1

    prod = v1_1 * w1_1
    # Test scalar multiplication here as well.
    expected = (
        2 * a + a * v1 + 2 * w1 +
        dr.sum((i, r), (j, r), x[i] * x[j] * v[i] * w[j])
    )
    assert prod.simplify() == expected.simplify()

    # Test the commutator operation.
    comm_v1v1 = v1 | v1
    assert comm_v1v1.simplify() == 0
    # Here the tensor subtraction can also be tested.
    comm_v1w1 = v1 | w1
    expected = (
        dr.sum((i, r), (j, r), x[i] * x[j] * v[i] * w[j]) -
        dr.sum((i, r), (j, r), x[j] * x[i] * w[i] * v[j])
    )
    assert comm_v1w1.simplify() == expected.simplify()

    alpha = symbols('alpha')
    assert alpha not in v1.free_vars
    tensor = v1 / alpha
    assert tensor.n_terms == 1
    terms = tensor.local_terms
    assert len(terms) == 1
    term = terms[0]
    assert term.sums == ((i, r),)
    assert term.amp == x[i] / alpha
    assert term.vecs == (v[i],)
    assert alpha in tensor.free_vars


def test_tensors_can_be_simplified_sums(free_alg):
    """Test the summation simplification facility of tensors."""
    dr = free_alg
    r = Range('D', 0, 2)

    a, b = symbols('a b')
    tensor = dr.sum(1) + dr.sum((a, r), 1) + dr.sum((a, r), (b, r), 1)
    res = tensor.simplify()
    assert res == dr.sum(7)


def test_tensors_can_be_differentiated(free_alg):
    """Test the analytic gradient computation of tensors."""

    dr = free_alg
    p = dr.names

    a = IndexedBase('a')
    b = IndexedBase('b')
    i, j, k, l, m, n = p.R_dumms[:6]

    tensor = dr.einst(
        a[i, j, k, l] * b[i, j] * conjugate(b[k, l])
    )

    # Test real analytic gradient.

    res = tensor.diff(b[i, j], real=True)
    expected = dr.einst(
        b[k, l] * (a[k, l, i, j] + a[i, j, k, l])
    )
    assert (res - expected).simplify() == 0

    # Test Wirtinger complex derivative.
    res, res_conj = [
        tensor.diff(b[m, n], wirtinger_conj=conj)
        for conj in [False, True]
    ]

    expected = dr.einst(
        conjugate(b[i, j]) * a[m, n, i, j]
    )
    expect_conj = dr.einst(
        a[i, j, m, n] * b[i, j]
    )

    for res_i, expected_i in [(res, expected), (res_conj, expect_conj)]:
        assert (res_i - expected_i).simplify() == 0

    # Test real analytic gradient with a simple test case.

    tensor = dr.einst(b[i, j] * b[j, i])
    grad = tensor.diff(b[i, j])
    assert (grad - 2 * b[j, i]).simplify() == 0


@pytest.mark.parametrize('full_balance', [True, False])
def test_tensors_can_be_substituted_scalars(free_alg, full_balance):
    """Test scalar substitution facility for tensors."""

    dr = free_alg
    p = dr.names

    x = IndexedBase('x')
    y = IndexedBase('y')
    z = IndexedBase('z')
    r = p.R
    i, j, k, l, m = p.R_dumms[:5]

    x_def = dr.define(
        x[i], dr.sum((j, r), y[j] * z[i])
    )
    orig = dr.sum((i, r), x[i] ** 2 * x[k])

    # k is free.
    expected = dr.sum(
        (i, r), (j, r), (l, r), (m, r),
        z[i] ** 2 * y[j] * y[l] * y[m] * z[k]
    )

    # Test different ways to perform the substitution.
    for res in [
        orig.subst(x[i], x_def.rhs, full_balance=full_balance),
        orig.subst_all([x_def], full_balance=full_balance),
        orig.subst_all([(x[i], x_def.rhs)], full_balance=full_balance),
        x_def.act(orig, full_balance=full_balance)
    ]:
        assert res.simplify() == expected.simplify()


@pytest.mark.parametrize('full_balance', [True, False])
@pytest.mark.parametrize('full_simplify', [True, False])
def test_tensors_can_be_substituted_vectors(
        free_alg, full_balance, full_simplify
):
    """Test vector substitution facility for tensors."""

    dr = free_alg
    p = dr.names

    x = IndexedBase('x')
    t = IndexedBase('t')
    u = IndexedBase('u')
    i, j = p.i, p.j
    v = p.v
    w = Vec('w')

    orig = dr.einst(x[i] * v[i])
    v_def = dr.einst(t[i, j] * w[j] + u[i, j] * w[j])

    dr.full_simplify = full_simplify
    res = orig.subst(v[i], v_def, full_balance=full_balance).simplify()
    dr.full_simplify = True

    expected = dr.einst(
        x[i] * t[i, j] * w[j] + x[i] * u[i, j] * w[j]
    ).simplify()
    assert res == expected


def test_tensors_can_be_rewritten(free_alg):
    """Test the amplitude rewriting facility for given vector patterns."""

    dr = free_alg
    p = dr.names
    v = Vec('v')
    a, b = p.R_dumms[:2]

    x = IndexedBase('x')
    o = IndexedBase('o')
    y = IndexedBase('y')
    z = IndexedBase('z')

    tensor = dr.einst(
        x[a] * v[a] + o[a, b] * y[b] * v[a] + z[b] * v[b]  # Terms to rewrite.
        + z[a, b] * v[a] * v[b]  # Terms to keep.
    )

    w = Wild('w')
    r = IndexedBase('r')
    rewritten, defs = tensor.rewrite(v[w], r[w])

    assert rewritten == dr.einst(
        z[a, b] * v[a] * v[b] + r[a] * v[a] + r[b] * v[b]
    )
    assert len(defs) == 2
    assert r[a] in defs
    assert defs[r[a]] == dr.einst(x[a] + o[a, b] * y[b])
    assert r[b] in defs
    assert defs[r[b]] == dr.sum(z[b])


def test_advanced_manipulations(free_alg):
    """Test advanced manipulations of tensors."""
    dr = free_alg
    p = dr.names
    i, j, k = p.i, p.j, p.k

    u = IndexedBase('u')
    v = IndexedBase('v')
    f = Vec('f')

    tensor = dr.einst(u[i, j] * f[j] + v[i, j] * f[j])
    assert tensor.n_terms == 2

    def has_u(term):
        """Test if a term have u tensor."""
        return term.amp.has(u)

    expect = dr.sum((j, p.R), u[i, j] * f[j])
    for res in [
        tensor.filter(has_u),
        tensor.bind(lambda x: [x] if has_u(x) else [])
    ]:
        assert res.n_terms == 1
        assert res == expect

    def subst_i(term):
        """Substitute i index in the terms."""
        return Term(term.sums, term.amp.xreplace({i: k}), term.vecs)

    expect = dr.sum((j, p.R), u[k, j] * f[j] + v[k, j] * f[j])
    for res in [
        tensor.map(subst_i),
        tensor.bind(lambda x: [subst_i(x)]),
        tensor.map2scalars(lambda x: x.xreplace({i: k}))
    ]:
        assert res.n_terms == 2
        assert res == expect

    alpha, beta = symbols('alpha beta')
    assert tensor.bind(
        lambda x: [Term(x.sums, x.amp * i_, x.vecs) for i_ in [alpha, beta]]
    ) == (tensor * alpha + tensor * beta)

    assert tensor.map2scalars(
        lambda x: x.xreplace({j: k})
    ) == dr.sum((j, p.R), u[i, k] * f[k] + v[i, k] * f[k])

    assert tensor.map2scalars(
        lambda x: x.xreplace({j: k}), skip_vecs=True
    ) == dr.sum((j, p.R), u[i, k] * f[j] + v[i, k] * f[j])


def test_tensor_method(free_alg):
    """Test tensor method can be injected."""

    tensor = free_alg.sum(10)
    assert tensor.get_one() == 1

    with pytest.raises(AttributeError):
        tensor.get_two()


def test_creating_empty_tensor_def(free_alg):
    """Test the creation of empty tensor definition."""
    dr = free_alg

    def_ = TensorDef(symbols('a'), (), dr.create_tensor([]))
    assert def_.rhs == 0


def test_tensor_def_creation_and_basic_properties(free_alg):
    """Test basic tensor definition creation and properties.

    Since tensor definitions are more frequently used for scalars, here we
    concentrate more on the scalar quantities than on vectors.
    """

    dr = free_alg
    p = dr.names
    i, j, k = p.R_dumms[:3]

    x = IndexedBase('x')
    o = IndexedBase('o')
    y = IndexedBase('y')

    rhs = o[i, j] * x[j]

    y_def = dr.define(y, (i, p.R), dr.sum((j, p.R), rhs))

    assert y_def.is_scalar
    assert y_def.rhs == dr.einst(rhs)
    assert y_def.lhs == y[i]
    assert y_def.base == y
    assert y_def.exts == [(i, p.R)]

    assert str(y_def) == 'y[i] = sum_{j} o[i, j]*x[j]'
    assert y_def.latex().strip() == r'y_{i} = \sum_{j \in R} x_{j}  o_{i,j}'

    y_def1 = dr.define(y[i], dr.sum((j, p.R), rhs))
    y_def2 = dr.define_einst(y[i], rhs)
    assert y_def1 == y_def
    assert y_def2 == y_def

    # Test the def_ utility.
    assert not dr.default_einst
    dr.default_einst = True
    y_def3 = dr.def_(y[i], rhs)
    dr.default_einst = False
    y_def4 = dr.def_(y[i], rhs)
    assert y_def3 == y_def
    assert y_def4 != y_def
    assert len(y_def4.local_terms) == 1
    assert len(y_def4.local_terms[0].sums) == 0

    # Test name archive utility for tensor definitions.
    dr.set_name(y_def4)
    assert p._y == y
    assert p.y == y_def4
    dr.unset_name(y_def4)
    assert not hasattr(p, '_y')
    assert not hasattr(p, 'y')

    # This tests the `act` method as well.
    assert y_def[1].simplify() == dr.einst(o[1, j] * x[j]).simplify()


def test_einstein_convention(free_alg):
    """Test Einstein summation convention utility.

    In this test, more complex aspects of the Einstein convention facility is
    tested.  Especially for the external indices and definition creation.
    """

    dr = free_alg
    p = dr.names

    o = IndexedBase('o')
    v = IndexedBase('v')
    w = IndexedBase('w')
    i, j = p.R_dumms[:2]

    raw_amp_1 = o[i, j] * v[j]
    raw_amp_2 = o[i, j] * w[j]
    raw_amp = raw_amp_1 + raw_amp_2

    for inp in [raw_amp, dr.sum(raw_amp)]:
        tensor, exts = dr.einst(inp, auto_exts=True)
        terms = tensor.local_terms
        assert all(i.sums == ((j, p.R),) for i in terms)
        assert {terms[0].amp, terms[1].amp} == {raw_amp_1, raw_amp_2}
        assert all(len(i.vecs) == 0 for i in terms)
        assert exts == {i}


def test_tensor_def_simplification(free_alg):
    """Test basic tensor definition simplification and dummy manipulation.
    """

    dr = free_alg
    p = dr.names

    i, j = p.R_dumms[:2]

    x = IndexedBase('x')
    o = IndexedBase('o')
    y = IndexedBase('y')

    y_def = dr.define(
        y, (j, p.R),
        dr.sum((i, p.R), o[j, i] * x[i]) - dr.einst(o[j, i] * x[i])
    )

    reset = y_def.reset_dumms()
    assert reset.base == y_def.base
    assert reset.exts == [(i, p.R)]
    assert reset.lhs == y[i]
    assert reset.rhs == dr.einst(o[i, j] * x[j]) - dr.einst(o[i, j] * x[j])

    simplified = reset.simplify()
    assert simplified.rhs == 0


def test_tensors_has_string_and_latex_form(free_alg, tmpdir):
    """Test the string and LaTeX form representation of tensors."""

    dr = free_alg
    p = dr.names

    v = p.v
    i = p.i
    x = IndexedBase('x')

    tensor = dr.einst(x[i] * v[i] - x[i] * v[i])
    zero = tensor.simplify()

    # The basic string form.
    orig = str(tensor)
    assert orig == 'sum_{i} x[i] * v[i]\n + sum_{i} -x[i] * v[i]'
    assert str(zero) == '0'

    # The LaTeX form.
    expected_terms = [
        r'\sum_{i \in R} x_{i}    \mathbf{v}_{i}',
        r'- \sum_{i \in R} x_{i}    \mathbf{v}_{i}'
    ]
    expected = ' '.join(expected_terms)
    assert tensor.latex() == expected

    assert tensor.latex(sep_lines=True) != expected
    assert tensor.latex(sep_lines=True).replace(r'\\ ', '') == expected

    assert tensor.latex(align_terms=True) != expected
    assert tensor.latex(align_terms=True).replace(' & ', '') == expected

    def proc(form, term, idx):
        """Process the terms in the LaTeX formatting."""
        assert term == tensor.local_terms[idx]
        assert form == expected_terms[idx]
        return 'N'

    assert tensor.latex(proc=proc).replace(' ', '') == 'N + N'.replace(' ', '')

    assert zero.latex() == '0'
    assert zero.latex(sep_lines=True) == '0'

    # Test the reporting facility.
    with tmpdir.as_cwd():
        title = 'Simple report test'
        sect = 'A simple tensor'
        descr = 'Nothing'

        filename = 'freealg.html'
        with dr.report(filename, title) as rep:
            rep.add(sect, tensor, description=descr)

        # Here we just simply test the existence of the file.
        assert os.path.isfile(filename)

        filename = 'freealg.pdf'
        with dr.report(filename, 'Simple report test') as rep:
            rep.add(
                sect, tensor, description=descr, env='dmath', sep_lines=False
            )
            rep.add(
                sect, tensor, description=descr, env='dmath',
                no_sum=True, scalar_mul=r'\invismult'
            )
        assert os.path.isfile('freealg.tex')
        if shutil.which('pdflatex') is not None:
            assert os.path.isfile(filename)


def test_drudge_has_default_properties(free_alg):
    """Test some basic default properties for drudge objects."""

    assert isinstance(free_alg.num_partitions, int)
    assert free_alg.full_simplify
    assert not free_alg.simple_merge


def test_tensor_can_be_added_summation(free_alg):
    """Test addition of new summations for existing tensors."""

    dr = free_alg
    p = dr.names
    i, j = p.R_dumms[:2]
    x = IndexedBase('x')
    y = IndexedBase('y')

    tensor = dr.sum((i, p.R), x[i, j] * y[j, i])

    for res in [
        dr.einst(tensor),
        dr.sum((j, p.R), tensor)
    ]:
        assert res == dr.einst(x[i, j] * y[j, i])


def test_pickling_tensors(free_alg):
    """Test tensors and definitions can be correctly pickled and unpickled."""

    dr = free_alg
    p = dr.names
    x = IndexedBase('x')
    v = Vec('v')
    b = Vec('b')

    tensor = dr.einst(x[p.i] * v[p.i])
    def_ = dr.define(b, tensor)
    serialized = pickle.dumps([tensor, def_])

    with pytest.raises(ValueError):
        pickle.loads(serialized)

    with dr.pickle_env():
        res = pickle.loads(serialized)

    assert res[0] == tensor
    assert res[1] == def_


def test_memoise(free_alg, tmpdir):
    """Test the memoise facility of drudge."""

    dr = free_alg
    n_calls = [0]
    filename = 'tmp.pickle'
    log = io.StringIO()

    def get_zero():
        n_calls[0] += 1
        return 0

    # Test the reporting facility.
    with tmpdir.as_cwd():
        assert dr.memoize(get_zero, filename, log=log) == 0
        assert dr.memoize(get_zero, filename, log=log) == 0
        assert dr.memoize(get_zero, filename) == 0
        assert n_calls[0] == 1
        assert len(log.getvalue().splitlines()) == 2


TEST_SIMPLE_DRS = """
x[i] <<= 1 / 2 * sum((i, R), m[i] * v[i])
y = sum_(range(10))
n = n_terms(x)
"""


def test_simple_drs(free_alg):
    """Test a simple drudge script."""
    dr = free_alg
    p = dr.names
    env = dr.exec_drs(TEST_SIMPLE_DRS)

    x = Vec('x')
    i = p.i
    def_ = dr.define_einst(x[i], Rational(1, 2) * p.m[i] * p.v[i])
    assert env['x'] == def_
    assert env['_x'] == x
    assert env['y'] == 45
    assert env['n'] == 1
    dr.unset_name(def_)

    # Test some drudge script specials about the free algebra environment.
    assert env['DRUDGE'] is dr
    assert env['sum_'] is sum


TEST_PICKLE_DRS = """
import pickle

symb = pickle.loads(pickle.dumps(f))
good_symb = symb == f

indexed = pickle.loads(pickle.dumps(f[i, j]))
good_indexed = indexed == f[i, j]

def_ = x[i] <= einst(f[i] * v[i]) / 2
def_serial = pickle.dumps(def_)
def_back = pickle.loads(def_serial)
"""


def test_pickle_within_drs(free_alg):
    """Test pickling inside drudge scripts."""

    dr = free_alg
    env = dr.exec_drs(TEST_PICKLE_DRS)

    assert env['good_symb']
    assert env['good_indexed']
    assert env['def_'] == env['def_back']
