# SPDX-License-Identifier: LGPL-3.0-or-later
import unittest

import numpy as np

# load grad of force module
from deepmd.tf.env import (
    GLOBAL_NP_FLOAT_PRECISION,
    GLOBAL_TF_FLOAT_PRECISION,
    op_module,
    tf,
)

from .common import (
    Data,
    force_dw_test,
    force_test,
    virial_dw_test,
    virial_test,
)


class Inter:
    def setUp(self, data, pbc=True, sess=None) -> None:
        self.sess = sess
        self.data = data
        self.natoms = self.data.get_natoms()
        self.ntypes = self.data.get_ntypes()
        self.sel_a = [12, 24]
        self.sel_r = [0, 0]
        self.rcut_a = -1
        self.rcut_r_smth = 2.45
        self.rcut_r = 10.0
        self.nnei_a = np.cumsum(self.sel_a)[-1]
        self.nnei_r = np.cumsum(self.sel_r)[-1]
        self.nnei = self.nnei_a + self.nnei_r
        self.ndescrpt_a = self.nnei_a * 4
        self.ndescrpt_r = self.nnei_r * 1
        self.ndescrpt = self.ndescrpt_a + self.ndescrpt_r
        davg = np.zeros([self.ntypes, self.ndescrpt])
        dstd = np.ones([self.ntypes, self.ndescrpt])
        self.t_avg = tf.constant(davg.astype(GLOBAL_NP_FLOAT_PRECISION))
        self.t_std = tf.constant(dstd.astype(GLOBAL_NP_FLOAT_PRECISION))
        if pbc:
            self.default_mesh = np.zeros(6, dtype=np.int32)
            self.default_mesh[3] = 2
            self.default_mesh[4] = 2
            self.default_mesh[5] = 2
        else:
            self.default_mesh = np.array([], dtype=np.int32)
        # make place holder
        self.coord = tf.placeholder(
            GLOBAL_TF_FLOAT_PRECISION, [None, self.natoms[0] * 3], name="t_coord"
        )
        self.box = tf.placeholder(GLOBAL_TF_FLOAT_PRECISION, [None, 9], name="t_box")
        self.type = tf.placeholder(tf.int32, [None, self.natoms[0]], name="t_type")
        self.tnatoms = tf.placeholder(tf.int32, [None], name="t_natoms")
        self.efield = tf.placeholder(
            GLOBAL_TF_FLOAT_PRECISION, [None, self.natoms[0] * 3], name="t_efield"
        )

    def _net(self, inputs, name, reuse=False):
        with tf.variable_scope(name, reuse=reuse):
            net_w = tf.get_variable(
                "net_w",
                [self.ndescrpt],
                GLOBAL_TF_FLOAT_PRECISION,
                tf.constant_initializer(self.net_w_i),
            )
        dot_v = tf.matmul(
            tf.reshape(inputs, [-1, self.ndescrpt]),
            tf.reshape(net_w, [self.ndescrpt, 1]),
        )
        return tf.reshape(dot_v, [-1])

    def comp_ef(self, dcoord, dbox, dtype, tnatoms, name, reuse=None):
        descrpt, descrpt_deriv, rij, nlist = op_module.prod_env_mat_a(
            dcoord,
            dtype,
            tnatoms,
            dbox,
            tf.constant(self.default_mesh),
            self.t_avg,
            self.t_std,
            rcut_a=self.rcut_a,
            rcut_r=self.rcut_r,
            rcut_r_smth=self.rcut_r_smth,
            sel_a=self.sel_a,
            sel_r=self.sel_r,
        )
        inputs_reshape = tf.reshape(descrpt, [-1, self.ndescrpt])
        atom_ener = self._net(inputs_reshape, name, reuse=reuse)
        atom_ener_reshape = tf.reshape(atom_ener, [-1, self.natoms[0]])
        energy = tf.reduce_sum(atom_ener_reshape, axis=1)
        net_deriv_ = tf.gradients(atom_ener, inputs_reshape)
        net_deriv = net_deriv_[0]
        net_deriv_reshape = tf.reshape(net_deriv, [-1, self.natoms[0] * self.ndescrpt])

        force = op_module.prod_force_se_a(
            net_deriv_reshape,
            descrpt_deriv,
            nlist,
            tnatoms,
            n_a_sel=self.nnei_a,
            n_r_sel=self.nnei_r,
        )
        virial, atom_vir = op_module.prod_virial_se_a(
            net_deriv_reshape,
            descrpt_deriv,
            rij,
            nlist,
            tnatoms,
            n_a_sel=self.nnei_a,
            n_r_sel=self.nnei_r,
        )
        return energy, force, virial

    def comp_f_dw(self, dcoord, dbox, dtype, tnatoms, name, reuse=None):
        energy, force, virial = self.comp_ef(dcoord, dbox, dtype, tnatoms, name, reuse)
        with tf.variable_scope(name, reuse=True):
            net_w = tf.get_variable(
                "net_w",
                [self.ndescrpt],
                GLOBAL_TF_FLOAT_PRECISION,
                tf.constant_initializer(self.net_w_i),
            )
        f_mag = tf.reduce_sum(tf.nn.tanh(force))
        f_mag_dw = tf.gradients(f_mag, net_w)
        assert len(f_mag_dw) == 1, "length of dw is wrong"
        return f_mag, f_mag_dw[0]

    def comp_v_dw(self, dcoord, dbox, dtype, tnatoms, name, reuse=None):
        energy, force, virial = self.comp_ef(dcoord, dbox, dtype, tnatoms, name, reuse)
        with tf.variable_scope(name, reuse=True):
            net_w = tf.get_variable(
                "net_w",
                [self.ndescrpt],
                GLOBAL_TF_FLOAT_PRECISION,
                tf.constant_initializer(self.net_w_i),
            )
        v_mag = tf.reduce_sum(virial)
        v_mag_dw = tf.gradients(v_mag, net_w)
        assert len(v_mag_dw) == 1, "length of dw is wrong"
        return v_mag, v_mag_dw[0]


class TestSmooth(Inter, tf.test.TestCase):
    # def __init__ (self, *args, **kwargs):
    #     data = Data()
    #     Inter.__init__(self, data)
    #     tf.test.TestCase.__init__(self, *args, **kwargs)
    #     self.controller = object()

    def setUp(self) -> None:
        self.places = 5
        data = Data()
        Inter.setUp(self, data, sess=self.cached_session().__enter__())

    def test_force(self) -> None:
        force_test(self, self, suffix="_smth")

    def test_virial(self) -> None:
        virial_test(self, self, suffix="_smth")

    def test_force_dw(self) -> None:
        force_dw_test(self, self, suffix="_smth")

    def test_virial_dw(self) -> None:
        virial_dw_test(self, self, suffix="_smth")


class TestSeAPbc(tf.test.TestCase):
    def test_pbc(self) -> None:
        data = Data()
        inter0 = Inter()
        inter1 = Inter()
        inter0.setUp(data, pbc=True, sess=self.cached_session().__enter__())
        inter1.setUp(data, pbc=False, sess=self.cached_session().__enter__())
        inter0.net_w_i = np.copy(np.ones(inter0.ndescrpt))
        inter1.net_w_i = np.copy(np.ones(inter1.ndescrpt))

        t_energy0, t_force0, t_virial0 = inter0.comp_ef(
            inter0.coord,
            inter0.box,
            inter0.type,
            inter0.tnatoms,
            name="test_sea_pbc_true",
        )
        t_energy1, t_force1, t_virial1 = inter1.comp_ef(
            inter1.coord,
            inter1.box,
            inter1.type,
            inter1.tnatoms,
            name="test_sea_pbc_false",
        )

        inter0.sess.run(tf.global_variables_initializer())
        inter1.sess.run(tf.global_variables_initializer())

        dcoord, dbox, dtype = data.get_data()

        [e0, f0, v0] = inter0.sess.run(
            [t_energy0, t_force0, t_virial0],
            feed_dict={
                inter0.coord: dcoord,
                inter0.box: dbox,
                inter0.type: dtype,
                inter0.tnatoms: inter0.natoms,
            },
        )
        [e1, f1, v1] = inter1.sess.run(
            [t_energy1, t_force1, t_virial1],
            feed_dict={
                inter1.coord: dcoord,
                inter1.box: dbox,
                inter1.type: dtype,
                inter1.tnatoms: inter1.natoms,
            },
        )

        self.assertAlmostEqual(e0[0], e1[0])
        np.testing.assert_almost_equal(f0[0], f1[0])
        np.testing.assert_almost_equal(v0[0], v1[0])

    def test_pbc_small_box(self) -> None:
        data0 = Data()
        data1 = Data(box_scale=2)
        inter0 = Inter()
        inter1 = Inter()
        inter0.setUp(data0, pbc=True, sess=self.cached_session().__enter__())
        inter1.setUp(data1, pbc=False, sess=self.cached_session().__enter__())
        inter0.net_w_i = np.copy(np.ones(inter0.ndescrpt))
        inter1.net_w_i = np.copy(np.ones(inter1.ndescrpt))

        t_energy0, t_force0, t_virial0 = inter0.comp_ef(
            inter0.coord,
            inter0.box,
            inter0.type,
            inter0.tnatoms,
            name="test_sea_pbc_sbox_true",
        )
        t_energy1, t_force1, t_virial1 = inter1.comp_ef(
            inter1.coord,
            inter1.box,
            inter1.type,
            inter1.tnatoms,
            name="test_sea_pbc_sbox_false",
        )

        inter0.sess.run(tf.global_variables_initializer())
        inter1.sess.run(tf.global_variables_initializer())

        dcoord, dbox, dtype = data0.get_data()
        [e0, f0, v0] = inter0.sess.run(
            [t_energy0, t_force0, t_virial0],
            feed_dict={
                inter0.coord: dcoord,
                inter0.box: dbox,
                inter0.type: dtype,
                inter0.tnatoms: inter0.natoms,
            },
        )
        dcoord, dbox, dtype = data1.get_data()
        [e1, f1, v1] = inter1.sess.run(
            [t_energy1, t_force1, t_virial1],
            feed_dict={
                inter1.coord: dcoord,
                inter1.box: dbox,
                inter1.type: dtype,
                inter1.tnatoms: inter1.natoms,
            },
        )

        self.assertAlmostEqual(e0[0], e1[0])
        np.testing.assert_almost_equal(f0[0], f1[0])
        np.testing.assert_almost_equal(v0[0], v1[0])


if __name__ == "__main__":
    unittest.main()
