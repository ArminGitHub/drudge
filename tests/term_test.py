"""Test some basic operations on tensor terms."""

import itertools
import pickle
import types

import pytest
from sympy import sympify, IndexedBase, KroneckerDelta, conjugate, Integer

from drudge import Range, Vec, Term, Perm, Group, IDENT, NEG, CONJ
from drudge.term import sum_term


@pytest.fixture
def mprod():
    """A fixture for a term looking like a matrix product.

    This can be used to test some basic operations on terms.
    """

    i, j, k = sympify('i, j, k')
    n = sympify('n')
    l = Range('L', 1, n)
    a = IndexedBase('a', shape=(n, n))
    b = IndexedBase('b', shape=(n, n))
    v = Vec('v')

    prod = sum_term(
        [(i, l), (j, l), (k, l)],
        a[i, j] * b[j, k] * v[i] * v[k]
    )

    assert len(prod) == 1
    return prod[0], types.SimpleNamespace(i=i, j=j, k=k, l=l, a=a, b=b, v=v,
                                          n=n)


def test_terms_has_basic_operations(mprod):
    """Test the basic operation on term, like creation."""

    prod, p = mprod

    assert len(prod.sums) == 3
    for sum_i, dumm in zip(prod.sums, [p.i, p.j, p.k]):
        assert len(sum_i) == 2
        assert sum_i[0] == dumm
        assert sum_i[1] == p.l

    assert prod.amp == p.a[p.i, p.j] * p.b[p.j, p.k]

    assert len(prod.vecs) == 2
    for vec_i, dumm in zip(prod.vecs, [p.i, p.k]):
        assert vec_i.base == p.v.base
        assert len(vec_i.indices) == 1
        assert vec_i.indices[0] == dumm

    # Here we create the same term with the basic Term constructor.
    ref_prod = Term(
        tuple((i, p.l) for i in [p.i, p.j, p.k]),
        p.a[p.i, p.j] * p.b[p.j, p.k],
        (p.v[p.i], p.v[p.k])
    )
    assert prod == ref_prod
    assert hash(prod) == hash(ref_prod)

    # Some different terms, for inequality testing.
    diff_sums = Term(prod.sums[:-1], prod.amp, prod.vecs)
    diff_amp = Term(prod.sums, Integer(2), prod.vecs)
    diff_vecs = Term(prod.sums, prod.amp, prod.vecs[:-1])
    for i in [diff_sums, diff_amp, diff_vecs]:
        assert prod != i
        assert hash(prod) != hash(i)

    assert str(prod) == 'sum_{i, j, k} a[i, j]*b[j, k] * v[i] * v[k]'
    assert repr(prod) == (
        "Term(sums="
        "[(i, Range('L', 1, n)), (j, Range('L', 1, n)), (k, Range('L', 1, n))],"
        " amp=a[i, j]*b[j, k],"
        " vecs=[Vec('v', (i)), Vec('v', (k))])"
    )


def test_terms_pickle_well(mprod):
    """Test terms to work well with pickle.

    This is an important test, since the terms are going to be trasmitted a
    lot during the parallel processing.
    """

    prod, _ = mprod
    serialized = pickle.dumps(prod)
    recovered = pickle.loads(serialized)
    assert prod == recovered
    assert hash(prod) == hash(recovered)


def test_terms_sympy_operations(mprod):
    """Test SymPy related operations in terms."""
    prod, p = mprod

    frees = prod.free_vars
    dumms = prod.dumms
    assert dumms == {p.i: p.l, p.j: p.l, p.k: p.l}
    assert frees == {p.a.args[0], p.b.args[0], p.n}


def test_terms_can_be_reset_dummies(mprod):
    """Test dummy resetting for terms."""

    prod, p = mprod

    w = sympify('w')
    excl = {w}

    dumms = {p.l: [w, p.i, p.j, p.k]}
    res, dummbegs = prod.reset_dumms(dumms, excl=excl)
    assert res == prod
    assert len(dummbegs) == 1
    assert p.l in dummbegs
    assert dummbegs[p.l] == 4

    res2, dummbegs2 = prod.reset_dumms(dumms, {p.l: 1})
    assert res2 == res
    assert dummbegs2 == dummbegs

    dumms = {p.l: [p.k, p.j, p.i]}
    res, dummbegs = prod.reset_dumms(dumms)
    expected = sum_term(
        [(p.k, p.l), (p.j, p.l), (p.i, p.l)],
        p.a[p.k, p.j] * p.b[p.j, p.i] * p.v[p.k] * p.v[p.i]
    )[0]
    assert res == expected
    assert len(dummbegs) == 1
    assert p.l in dummbegs
    assert dummbegs[p.l] == 3


def test_delta_can_be_simplified(mprod):
    """Test the delta simplification facility."""

    _, p = mprod
    i, j, k = p.i, p.j, p.k
    l = p.l
    dumms = {l: [i, j, k]}

    term = sum_term(
        [(i, l), (j, l)],
        KroneckerDelta(i, j) * KroneckerDelta(j, k) * p.v[i]
    )[0]

    # If we do not tell which range k belongs, a delta should be kept.
    #
    # Here either i or j could be removed.
    res = term.simplify_deltas([]).reset_dumms(dumms)
    assert res == (
        sum_term([(j, l)], KroneckerDelta(j, k) * p.v[j])[0]
    ).reset_dumms(dumms)

    # When the range for k is given, more simplification comes.
    res = term.simplify_deltas([lambda x: p.l])
    assert res == sum_term([], p.v[k])[0]


def test_simple_terms_can_be_canonicalized():
    """Test the canonicalization of very simple terms.

    In this test, all the terms has very simple appearance.  So rather than
    testing the canonicalization really canonicalizes all the equivalent
    forms, here we check if the canonicalized form is the most intuitive form
    that we expect.
    """

    l = Range('L')
    x = IndexedBase('x')
    i, j = sympify('i, j')

    # A term without the vector part, canonicalization without symmetry.
    term = sum_term([(j, l), (i, l)], x[i, j])[0]
    res = term.canon()
    expected = sum_term([(i, l), (j, l)], x[i, j])[0]
    assert res == expected

    # A term without the vector part, canonicalization with symmetry.
    m = Range('M')
    term = sum_term([(j, m), (i, l)], x[j, i])[0]
    for neg, conj in itertools.product([IDENT, NEG], [IDENT, CONJ]):
        acc = neg | conj
        group = Group([Perm([1, 0], acc)])
        res = term.canon(symms={x: group})
        expected_amp = x[i, j]
        if neg == NEG:
            expected_amp *= -1
        if conj == CONJ:
            expected_amp = conjugate(expected_amp)
        expected = sum_term([(i, l), (j, m)], expected_amp)[0]
        assert res == expected
        continue

    # In the absence of symmetry, the two indices should not be permuted.
    res = term.canon()
    expected = sum_term([(i, l), (j, m)], x[j, i])[0]
    assert res == expected

    # Now we add vectors to the terms.
    v = Vec('v')
    term = sum_term([(i, l), (j, l)], v[i] * v[j])[0]

    # Without anything added, it should already be in the canonical form.
    assert term.canon() == term

    # When we flip the colour of the vectors, we should get something different.
    res = term.canon(vec_colour=lambda idx, vec, term: -idx)
    expected = sum_term([(j, l), (i, l)], v[i] * v[j])[0]
    assert res == expected


def test_canonicalization_of_matrix_product(mprod):
    """Test the canonicalization of the matrix product test case."""

    prod, p = mprod

    res = prod.canon()

    # The indices used in the vectors should come earlier.
    sums = prod.sums
    new_sums = (sums[0], sums[2], sums[1])
    expected = prod.map(lambda x: x, sums=new_sums)
    assert res == expected
