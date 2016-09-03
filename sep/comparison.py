#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2016 Stephane Caron <stephane.caron@normalesup.org>
#
# This file is part of 3d-mpc <https://github.com/stephane-caron/3d-mpc>.
#
# 3d-mpc is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# 3d-mpc is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# 3d-mpc. If not, see <http://www.gnu.org/licenses/>.

SHOW_ROBOT = False

import IPython
import numpy
import os
import sys
import thread
import threading
import time

try:
    import pymanoid
except ImportError:
    script_path = os.path.realpath(__file__)
    sys.path.append(os.path.dirname(script_path) + '/../pymanoid')
    import pymanoid
    from pymanoid.tasks import COMTask

from numpy.random import random
from scipy.spatial import ConvexHull
from polygon import compute_static_polygon_bretl
from polygon import compute_static_polygon_cdd_hull
from polygon import compute_static_polygon_pyparma_hull
from polygon import compute_static_polygon_cdd_only

try:
    from hrp4_pymanoid import HRP4 as RobotModel
except ImportError:
    from pymanoid.robots import JVRC1 as RobotModel


cyan = (0., 0.5, 0.5, 0.5)
robot = None
custom_mass = 39
robot_mass = 39  # [kg], updated once robot model is loaded
dt = 3e-2  # [s]
robot_lock = threading.Lock()
green = (0., 0.5, 0., 0.5)
gui_handles = {}
handles = [None, None]
magenta = (0.5, 0., 0.5, 0.5)
yellow = (0.5, 0.5, 0., 0.5)
black = (0., 0., 0., 0.5)
saved_handles = []
z_high = 1.5
z_mid = 0.75

# IK params
qd_lim = 10.
K_doflim = 5.
G_com = 1. / dt
G_link = 0.9 / dt
w_link = 100.
w_com = 005.
w_reg = 001.
screenshot = False


def run_ik_thread():
    while True:
        with robot_lock:
            if robot is not None:
                robot.step_ik(dt)
            com_target.set_x(outbox.x)
            com_target.set_y(outbox.y)
            com_target.set_z(outbox.z - z_high + z_mid)
        time.sleep(dt)


def draw_com_polygon(vertices, color):
    return pymanoid.draw_polygon(
        [(x[0], x[1], com_target.z) for x in vertices],
        normal=[0, 0, 1], combined='m.-#', color=color, pointsize=0.02,
        linewidth=3.)


def draw_cdd_thread():
    while True:
        try:
            vertices = compute_static_polygon_cdd_hull(contacts)
            if vertices:
                gui_handles['cdd'] = draw_com_polygon(vertices, magenta)
        except Exception as e:
            print "draw_cdd_thread:", e
            continue
        time.sleep(1e-2)


def draw_pyparma_thread():
    while True:
        try:
            vertices = compute_static_polygon_pyparma_hull(contacts)
            if vertices:
                gui_handles['pyparma'] = draw_com_polygon(vertices, yellow)
        except Exception as e:
            print "draw_pyparma_thread:", e
            continue
        time.sleep(1e-2)


def draw_bretl_thread():
    while True:
        try:
            vertices = compute_static_polygon_bretl(contacts)
            gui_handles['bretl'] = draw_com_polygon(vertices, cyan)
        except Exception as e:
            print "draw_bretl_thread:", e
            continue
        time.sleep(1e-2)


def draw_cdd_only_thread():
    while True:
        try:
            # you can vary ``custom_mass`` to check that it has no effect
            vertices = compute_static_polygon_cdd_only(contacts, custom_mass)
            gui_handles['cdd_only'] = draw_com_polygon(vertices, black)
        except Exception as e:
            print "draw_cdd_only_thread:", e
            continue
        time.sleep(1e-2)


def show_plots(B, c, lim=1.):
    import pylab
    hull = ConvexHull([row for row in B])
    pylab.ion()
    pylab.subplot(121)
    xvals, yvals = zip(*[row for row in B])
    xmin, xmax, ymin, ymax = -lim, +lim, -lim, +lim
    pylab.plot(xvals, yvals, 'go')
    for (i, j) in hull.simplices:
        x1, y1 = B[i]
        x2, y2 = B[j]
        pylab.plot([x1, x2], [y1, y2], 'r-')
    pylab.subplot(122)
    for (i, row) in enumerate(B):
        if abs(row[1]) > 1e-10:
            xvals = [xmin, xmax]
            yvals = [(float(c[i]) - float(x) * row[0]) / row[1] for x in xvals]
            pylab.plot(xvals, yvals, 'b-')
        elif abs(row[0]) > 1e-10:
            xvals = [float(c[i]) / row[0]] * 2
            yvals = [ymin, ymax]
            pylab.plot(xvals, yvals, 'g-')
        else:
            print "discarding row:", row
    pylab.xlim((xmin, xmax))
    pylab.ylim((ymin, ymax))
    pylab.plot(0., 0., 'ro')


def prepare_screenshot(ambient=1., diffuse=0.8):
    global screenshot
    screenshot = True
    outbox.set_visible(False)
    viewer.SetBkgndColor([1., 1., 1.])
    with robot_lock:
        robot.set_transparency(0)
        for link in robot.rave.GetLinks():
            if len(link.GetGeometries()) > 0:
                geom = link.GetGeometries()[0]
                geom.SetAmbientColor([ambient] * 3)
                geom.SetDiffuseColor([diffuse] * 3)
    time.sleep(1)  # wait for screenshot=True to propagate
    gui_handles['bretl'][0] = None
    gui_handles['bretl'][1] = None
    gui_handles['bretl'][2] = None
    gui_handles['cdd_only'][0] = None
    gui_handles['cdd_only'][1] = None
    gui_handles['cdd_only'][2] = None
    gui_handles['pyparma'][0] = None
    gui_handles['pyparma'][1] = None
    gui_handles['pyparma'][2] = None
    viewer.SetCamera([
        [0.93083067,  0.22113073, -0.29095612,  2.02004194],
        [0.36381928, -0.48557605,  0.79489083, -2.47407389],
        [0.03449347, -0.84576421, -0.53244071,  2.58443999],
        [0.,  0.,  0.,  1.]])


def benchmark():
    # first, we call this one once as it will round contacts RPY
    compute_static_polygon_cdd_only(contacts, robot_mass)
    print ""
    print "Benchmarking computation times"
    print "------------------------------"
    function_calls = ['compute_static_polygon_cdd_hull(contacts)',
                      'compute_static_polygon_pyparma_hull(contacts)',
                      'compute_static_polygon_bretl(contacts)',
                      'compute_static_polygon_cdd_only(contacts, robot_mass)']
    for call in function_calls:
        print "\n%%timeit %s" % call
        for _ in xrange(1):
            IPython.get_ipython().magic(u'timeit %s' % call)


def sample_contacts():
    for c in contacts.contacts:
        c.set_pos(random(3))
        c.set_rpy(0. * random(3))
    try:
        # compute_static_polygon_cdd_only(contacts, custom_mass)
        compute_static_polygon_cdd_hull(contacts)
    except:
        return sample_contacts()


if __name__ == "__main__":
    if IPython.get_ipython() is None:
        # we use IPython (in interactive mode) for the %timeit function
        print "Usage: ipython -i %s" % os.path.basename(__file__)
        exit(-1)

    pymanoid.init()
    viewer = pymanoid.get_env().GetViewer()
    viewer.SetBkgndColor([.6, .6, .8])
    viewer.SetCamera(numpy.array([
        [0.60587192, -0.36596244,  0.70639274, -2.4904027],
        [-0.79126787, -0.36933163,  0.48732874, -1.6965636],
        [0.08254916, -0.85420468, -0.51334199,  2.79584694],
        [0.,  0.,  0.,  1.]]))
    if SHOW_ROBOT:
        robot = RobotModel(download_if_needed=True)
        robot.set_transparency(0.2)
        robot_mass = robot.mass

    fname = sys.argv[1] if len(sys.argv) > 1 else 'stances/figure2-triple.json'
    contacts = pymanoid.ContactSet.from_json(fname)

    com_target = pymanoid.Cube(0.01, visible=True)
    outbox = pymanoid.Cube(0.02, color='b')

    if 'figure2-single.json' in fname:
        outbox.set_pos([0.,  0.,  z_high])
    elif 'figure2-double.json' in fname or 'figure2-triple.json' in fname:
        outbox.set_pos([0.3,  0.04,  z_high])
    else:
        warn("Unknown contact set, you will have to set the COM position.")

    if SHOW_ROBOT:
        with robot_lock:
            robot.set_dof_values(robot.q_halfsit)
            robot.set_active_dofs(
                robot.chest + robot.legs + robot.arms + robot.free)
            robot.init_ik()
            robot.generate_posture(contacts)
            robot.ik.add_task(COMTask(robot, com_target))

    print ""
    print "Static-equilibrium polygon computations"
    print "======================================="
    print ""
    print "Legend:"
    print "- Magenta area: computed using cdd + Qhull"
    print "- Yellow area: computed using Parma + Qhull"
    print "- Green area: computed using Bretl and Lall's method"
    print "- Black area: computed using cdd only"
    print ""
    print "Run ``benchmark()`` to compare computation times."
    print ""
    print "Run ``sample_contacts()`` to sample a new contact configuration."
    print ""

    # benchmark()

    thread.start_new_thread(run_ik_thread, ())
    thread.start_new_thread(draw_cdd_thread, ())
    thread.start_new_thread(draw_bretl_thread, ())
    thread.start_new_thread(draw_pyparma_thread, ())
    thread.start_new_thread(draw_cdd_only_thread, ())
    contacts.start_force_thread(com_target, robot_mass, dt=1e-2)
