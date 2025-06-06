#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr 19 14:55:02 2021

@author: Luca Azzolin

Copyright 2021 Luca Azzolin

Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""
import csv
import os
import pickle
import subprocess

import numpy as np
import pandas as pd
import pymesh
import pymeshlab
import vtk
from carputils import tools
from vtk.numpy_interface import dataset_adapter as dsa

import Methods_RA as Method
from Atrial_LDRBM.LDRBM.Fiber_LA.Methods_LA import generate_spline_points
from vtk_opencarp_helper_methods.AugmentA_methods.vtk_operations import vtk_thr
from vtk_opencarp_helper_methods.openCARP.exporting import write_to_pts, write_to_elem, write_to_lon
from vtk_opencarp_helper_methods.vtk_methods.converters import vtk_to_numpy
from vtk_opencarp_helper_methods.vtk_methods.exporting import vtk_xml_unstructured_grid_writer, \
    vtk_unstructured_grid_writer, vtk_obj_writer
from vtk_opencarp_helper_methods.vtk_methods.filters import apply_vtk_geom_filter, clean_polydata, vtk_append, \
    apply_extract_cell_filter, get_cells_with_ids
from vtk_opencarp_helper_methods.vtk_methods.finder import find_closest_point

EXAMPLE_DIR = os.path.dirname(os.path.realpath(__file__))


def parser():
    # Generate the standard command line parser
    parser = tools.standard_parser()
    # Add arguments
    parser.add_argument('--mesh',
                        type=str,
                        default="/Users/Patymardi/Documents/Promotion/Valencia/meshes_testing/meshes/20210729/20210729_res",
                        help='path to meshname')
    parser.add_argument('--mesh_type',
                        default='bilayer',
                        choices=['vol',
                                 'bilayer'],
                        help='Mesh type')
    parser.add_argument('--debug',
                        type=int,
                        default=0,
                        help='set to 1 to debug code')
    parser.add_argument('--scale',
                        type=int,
                        default=1,
                        help='normal unit is mm, set scaling factor if different')

    return parser


def jobID(args):
    ID = f'{args.mesh}_fibers'
    return ID


@tools.carpexample(parser, jobID)
def run(args, job):
    la_epi = Method.smart_reader(job.ID + "/result_LA/LA_epi_with_fiber.vtu")

    model = Method.smart_reader(job.ID + "/result_RA/RA_epi_with_fiber.vtu")

    df = pd.read_csv(args.mesh + "_surf/rings_centroids.csv")

    CS_p = np.array(df["CS"])

    print('[Step 3] Generate Bridges and Bilayer... ')

    add_free_bridge(args, la_epi, model, CS_p, df, job)

    print('[Step 3] Generate Bilayer...done! ')


def add_free_bridge(args, la_epi, ra_epi, CS_p, df, job):
    ########################################
    with open(os.path.join(EXAMPLE_DIR, '../../element_tag.csv')) as f:
        tag_dict = {}
        reader = csv.DictReader(f)
        for row in reader:
            tag_dict[row['name']] = row['tag']

    bridge_radius = 1.65 * args.scale

    bachmann_bundel_left = int(tag_dict['bachmann_bundel_left'])
    bachmann_bundel_right = int(tag_dict['bachmann_bundel_right'])
    bachmann_bundel_internal = int(tag_dict['bachmann_bundel_internal'])
    middle_posterior_bridge_left = int(tag_dict['middle_posterior_bridge_left'])
    middle_posterior_bridge_right = int(tag_dict['middle_posterior_bridge_right'])
    upper_posterior_bridge_left = int(tag_dict['upper_posterior_bridge_left'])
    upper_posterior_bridge_right = int(tag_dict['upper_posterior_bridge_right'])
    coronary_sinus_bridge_left = int(tag_dict['coronary_sinus_bridge_left'])
    coronary_sinus_bridge_right = int(tag_dict['coronary_sinus_bridge_right'])
    right_atrial_septum_epi = int(tag_dict['right_atrial_septum_epi'])
    left_atrial_wall_epi = int(tag_dict["left_atrial_wall_epi"])
    mitral_valve_epi = int(tag_dict["mitral_valve_epi"])
    tricuspid_valve_epi = int(tag_dict["tricuspid_valve_epi"])

    # la_epi = vtk_thr(la, 0 "CELLS", "elemTag", left_atrial_wall_epi)
    la_epi_surface = apply_vtk_geom_filter(la_epi)

    # ra_epi = vtk_thr(la, 0 "CELLS", "elemTag", left_atrial_wall_epi)

    ra_epi_surface = apply_vtk_geom_filter(ra_epi)

    SVC_p = np.array(df["SVC"])
    IVC_p = np.array(df["IVC"])
    TV_p = np.array(df["TV"])

    ra_septum = vtk_thr(ra_epi, 2, "CELLS", "elemTag", right_atrial_septum_epi, right_atrial_septum_epi)
    la_wall = vtk_thr(la_epi, 2, "CELLS", "elemTag", left_atrial_wall_epi, left_atrial_wall_epi)
    mv_la = vtk_thr(la_epi, 2, "CELLS", "elemTag", mitral_valve_epi, mitral_valve_epi)
    tv_ra = vtk_thr(ra_epi, 2, "CELLS", "elemTag", tricuspid_valve_epi, tricuspid_valve_epi)

    # Find middle and upper posterior bridges points
    point_septum_SVC = ra_septum.GetPoint(find_closest_point(ra_septum, SVC_p))
    point_septum_IVC = ra_septum.GetPoint(find_closest_point(ra_septum, IVC_p))

    SVC_IVC_septum_path = Method.dijkstra_path_coord(ra_epi_surface, point_septum_SVC, point_septum_IVC)

    middle_posterior_bridge_point = SVC_IVC_septum_path[int(len(SVC_IVC_septum_path) * 0.6), :]

    upper_posterior_bridge_point = SVC_IVC_septum_path[int(len(SVC_IVC_septum_path) * 0.4), :]

    mpb_tube, mpb_sphere_1, mpb_sphere_2, mpb_fiber = Method.create_free_bridge_semi_auto(la_epi_surface,
                                                                                          ra_epi_surface,
                                                                                          middle_posterior_bridge_point,
                                                                                          bridge_radius)
    Method.smart_bridge_writer(mpb_tube, mpb_sphere_1, mpb_sphere_2, "middle_posterior_bridge", job)

    upb_tube, upb_sphere_1, upb_sphere_2, upb_fiber = Method.create_free_bridge_semi_auto(la_epi_surface,
                                                                                          ra_epi_surface,
                                                                                          upper_posterior_bridge_point,
                                                                                          bridge_radius)
    Method.smart_bridge_writer(upb_tube, upb_sphere_1, upb_sphere_2, "upper_posterior_bridge", job)

    # Coronary sinus bridge point

    # it happened that the point is too close to the edge and the heart is not found
    point_CS_on_MV = mv_la.GetPoint(find_closest_point(mv_la, CS_p + TV_p * 0.1))

    point_CS_bridge = ra_septum.GetPoint(find_closest_point(ra_septum, point_CS_on_MV))

    csb_tube, csb_sphere_1, csb_sphere_2, csb_fiber = Method.create_free_bridge_semi_auto(la_epi_surface,
                                                                                          ra_epi_surface,
                                                                                          point_CS_bridge,
                                                                                          bridge_radius)
    Method.smart_bridge_writer(csb_tube, csb_sphere_1, csb_sphere_2, "coronary_sinus_bridge", job)

    if args.mesh_type == "vol":
        bilayer_epi = vtk_append([la_epi, ra_epi])

        tag = np.zeros((bilayer_epi.GetNumberOfCells(),), dtype=int)
        tag[:la_epi.GetNumberOfCells()] = vtk_to_numpy(la_epi.GetCellData().GetArray('elemTag'))
        tag[la_epi.GetNumberOfCells():] = vtk_to_numpy(ra_epi.GetCellData().GetArray('elemTag'))

        meshNew = dsa.WrapDataObject(bilayer_epi)
        meshNew.CellData.append(tag, "elemTag")

        vtk_xml_unstructured_grid_writer(job.ID + "/result_RA/la_ra_res.vtu", vtk_append([meshNew.VTKObject]))
    elif args.mesh_type == "bilayer":

        la_e = Method.smart_reader(job.ID + "/result_LA/LA_epi_with_fiber.vtu")
        la_e = apply_vtk_geom_filter(la_e)

        ra_e = Method.smart_reader(job.ID + "/result_RA/RA_epi_with_fiber.vtu")
        ra_e = apply_vtk_geom_filter(ra_e)

        append_filter = vtk.vtkAppendFilter()
        append_filter.AddInputData(la_e)
        append_filter.AddInputData(ra_e)
        append_filter.Update()  # la_ra_usg

        # Good till here!
        vtk_xml_unstructured_grid_writer(job.ID + "/result_RA/LA_epi_RA_epi_with_tag.vtu", append_filter.GetOutput())

    bridge_list = ['BB_intern_bridges', 'coronary_sinus_bridge', 'middle_posterior_bridge', 'upper_posterior_bridge']
    for var in bridge_list:
        mesh_A = pymesh.load_mesh(job.ID + "/bridges/" + str(var) + "_tube.obj")
        mesh_B = pymesh.load_mesh(job.ID + "/bridges/" + str(var) + "_sphere_1.obj")
        mesh_C = pymesh.load_mesh(job.ID + "/bridges/" + str(var) + "_sphere_2.obj")

        output_mesh_1 = pymesh.boolean(mesh_A, mesh_B, operation="union", engine="igl")

        output_mesh = pymesh.boolean(output_mesh_1, mesh_C, operation="union", engine="igl")

        m = pymeshlab.Mesh(output_mesh.vertices, output_mesh.faces)
        # create a new MeshSet
        ms = pymeshlab.MeshSet()
        # add the mesh to the MeshSet
        ms.add_mesh(m, "bridge_mesh")
        # apply filter
        ms.remeshing_isotropic_explicit_remeshing(iterations=5, targetlen=0.4 * args.scale, adaptive=True)
        ms.save_current_mesh(job.ID + "/bridges/" + str(var) + "_bridge_resampled.obj", \
                             save_vertex_color=False, save_vertex_normal=False, save_face_color=False,
                             save_wedge_texcoord=False, save_wedge_normal=False)

        subprocess.run(["meshtool",
                        "generate",
                        "mesh",
                        "-ofmt=vtk",
                        "-prsv_bdry=1",
                        "-surf=" + job.ID + "/bridges/" + str(var) + "_bridge_resampled.obj",
                        "-outmsh=" + job.ID + "/bridges/" + str(var) + "_bridge_resampled.vtk"])

    la_ra_usg = append_filter.GetOutput()  # this has already elemTag

    print('reading done!')

    bridge_list = ['BB_intern_bridges', 'coronary_sinus_bridge', 'middle_posterior_bridge', 'upper_posterior_bridge']
    earth_cell_ids_list = []
    for var in bridge_list:
        print(var)

        reader = vtk.vtkUnstructuredGridReader()
        reader.SetFileName(job.ID + "/bridges/" + str(var) + '_bridge_resampled.vtk')
        reader.Update()
        bridge_usg = reader.GetOutput()

        locator = vtk.vtkStaticPointLocator()
        locator.SetDataSet(la_ra_usg)
        locator.BuildLocator()

        intersection_points = bridge_usg.GetPoints().GetData()
        intersection_points = vtk_to_numpy(intersection_points)

        earth_point_ids_temp = vtk.vtkIdList()
        earth_point_ids = vtk.vtkIdList()
        for i in range(len(intersection_points)):
            locator.FindPointsWithinRadius(0.7 * args.scale, intersection_points[i], earth_point_ids_temp)
            for j in range(earth_point_ids_temp.GetNumberOfIds()):
                earth_point_ids.InsertNextId(earth_point_ids_temp.GetId(j))

        earth_cell_ids_temp = vtk.vtkIdList()
        earth_cell_ids = vtk.vtkIdList()
        for i in range(earth_point_ids.GetNumberOfIds()):
            la_ra_usg.GetPointCells(earth_point_ids.GetId(i), earth_cell_ids_temp)
            for j in range(earth_cell_ids_temp.GetNumberOfIds()):
                earth_cell_ids.InsertNextId(earth_cell_ids_temp.GetId(j))
                earth_cell_ids_list += [earth_cell_ids_temp.GetId(j)]

        earth = apply_vtk_geom_filter(apply_extract_cell_filter(la_ra_usg, earth_cell_ids))
        earth = clean_polydata(earth)

        # meshNew = dsa.WrapDataObject(cleaner.GetOutput())
        vtk_obj_writer(job.ID + "/bridges/" + str(var) + "_earth.obj", earth)
        # Here

        print("Extracted earth")
        cell_id_all = []
        for i in range(la_ra_usg.GetNumberOfCells()):
            cell_id_all.append(i)

        la_diff = list(set(cell_id_all).difference(set(earth_cell_ids_list)))
        append_filter = vtk.vtkAppendFilter()
        append_filter.MergePointsOn()
        # append_filter.SetTolerance(0.01*args.scale)

        append_filter.AddInputData(get_cells_with_ids(la_ra_usg, la_diff))

        if args.debug:
            vtk_xml_unstructured_grid_writer(job.ID + "/result_RA/" + str(var) + "_append_earth.vtu",
                                             append_filter.GetOutput())

    filename = job.ID + '/bridges/bb_fiber.dat'
    f = open(filename, 'rb')
    bb_fiber = pickle.load(f)

    bb_fiber_points_data = vtk_to_numpy(generate_spline_points(bb_fiber).GetPoints().GetData())

    print("Union between earth and bridges")
    for var in bridge_list:

        mesh_D = pymesh.load_mesh(job.ID + "/bridges/" + str(var) + "_bridge_resampled.obj")
        mesh_E = pymesh.load_mesh(job.ID + "/bridges/" + str(var) + "_earth.obj")
        # # Warning: set -1 if pts normals are pointing outside
        # # Use union if the endo normals are pointing outside
        # output_mesh_2 = pymesh.boolean(mesh_D, mesh_E, operation="union", engine="corefinement")
        if args.mesh_type == "bilayer":
            # Use difference if the endo normals are pointing inside
            output_mesh_2 = pymesh.boolean(mesh_E, mesh_D, operation="difference", engine="corefinement")
            pymesh.save_mesh(job.ID + "/bridges/" + str(var) + "_union_to_resample.obj", output_mesh_2, ascii=True)
        else:
            output_mesh_2 = pymesh.boolean(mesh_D, mesh_E, operation="union", engine="corefinement")
            pymesh.save_mesh(job.ID + "/bridges/" + str(var) + "_union_to_resample.obj", output_mesh_2, ascii=True)

        print("Union between earth and bridges in " + var)

        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(job.ID + "/bridges/" + str(var) + "_union_to_resample.obj")
        ms.remeshing_isotropic_explicit_remeshing(iterations=5, targetlen=0.4 * args.scale, adaptive=True)
        ms.save_current_mesh(job.ID + "/bridges/" + str(var) + "_union.obj", \
                             save_vertex_color=False, save_vertex_normal=False, save_face_color=False,
                             save_wedge_texcoord=False, save_wedge_normal=False)

        if args.mesh_type == "vol":
            subprocess.run(["meshtool",
                            "generate",
                            "mesh",
                            "-ofmt=vtk",
                            "-prsv_bdry=1",
                            # "-scale={}".format(0.4*args.scale),
                            "-surf=" + job.ID + "/bridges/" + str(var) + "_union.obj",
                            "-outmsh=" + job.ID + "/bridges/" + str(var) + "_union_mesh.vtk"])

            reader = vtk.vtkUnstructuredGridReader()  # vtkXMLUnstructuredGridReader
            reader.SetFileName(job.ID + "/bridges/" + str(var) + "_union_mesh.vtk")
            reader.Update()
            bridge_union = reader.GetOutput()
        elif args.mesh_type == "bilayer":

            reader = vtk.vtkOBJReader()
            reader.SetFileName(job.ID + "/bridges/" + str(var) + "_union.obj")
            reader.Update()
            bridge_union = vtk.vtkUnstructuredGrid()
            bridge_union.DeepCopy(reader.GetOutput())

        tag = np.zeros(bridge_union.GetNumberOfCells(), dtype=int)

        if var == 'BB_intern_bridges':
            tag[:] = bachmann_bundel_internal
        elif var == 'coronary_sinus_bridge':
            tag[:] = coronary_sinus_bridge_left
        elif var == 'middle_posterior_bridge':
            tag[:] = middle_posterior_bridge_left
        elif var == 'upper_posterior_bridge':
            tag[:] = upper_posterior_bridge_left

        fiber = np.ones((bridge_union.GetNumberOfCells(), 3), dtype="float32")

        if var == 'BB_intern_bridges':
            fiber = Method.assign_element_fiber_around_path_within_radius(bridge_union, bb_fiber_points_data,
                                                                          3 * args.scale, fiber, smooth=True)
        elif var == 'coronary_sinus_bridge':
            fiber[:] = csb_fiber
        elif var == 'middle_posterior_bridge':
            fiber[:] = mpb_fiber
        elif var == 'upper_posterior_bridge':
            fiber[:] = upb_fiber

        meshNew = dsa.WrapDataObject(bridge_union)
        meshNew.CellData.append(tag, "elemTag")
        meshNew.CellData.append(fiber, "fiber")
        vtk_unstructured_grid_writer(job.ID + "/bridges/" + str(var) + "_union_mesh.vtu", meshNew.VTKObject)
        append_filter.AddInputData(meshNew.VTKObject)  # Check here if we still have the element tag

    append_filter.MergePointsOn()  # here we lose the tags
    append_filter.Update()

    epi = append_filter.GetOutput()

    vtk_xml_unstructured_grid_writer(job.ID + "/result_RA/LA_RA_with_bundles.vtu", epi)
    epi = Method.generate_sheet_dir(args, epi, job)

    vtk_xml_unstructured_grid_writer(job.ID + "/result_RA/LA_RA_with_sheets.vtu", epi)
    if args.mesh_type == "bilayer":

        vtk_xml_unstructured_grid_writer(job.ID + "/result_RA/la_ra_epi_with_sheets.vtu", epi)
        reader = vtk.vtkXMLUnstructuredGridReader()
        reader.SetFileName(job.ID + "/result_RA/RA_CT_PMs.vtu")
        reader.Update()
        ra_endo = reader.GetOutput()

        reader = vtk.vtkXMLUnstructuredGridReader()
        reader.SetFileName(job.ID + "/result_LA/LA_endo_with_fiber.vtu")
        reader.Update()
        la_endo = reader.GetOutput()

        biatrial_endo = vtk_append([la_endo, ra_endo])

        vtk_xml_unstructured_grid_writer(job.ID + "/result_RA/append_LA_endo_RA_endo.vtu", biatrial_endo)
        endo = Method.move_surf_along_normals(biatrial_endo, 0.1 * args.scale,
                                              1)  # # Warning: set -1 if pts normals are pointing outside

        vtk_unstructured_grid_writer(job.ID + "/result_RA/la_ra_endo.vtu", endo)
        bilayer = Method.generate_bilayer(endo, epi, 0.12 * args.scale)

        Method.write_bilayer(bilayer, args, job)

    else:
        file_name = job.ID + "/result_RA/LA_RA_vol_with_fiber"
        vtk_xml_unstructured_grid_writer(f"{file_name}.vtu", epi)

        pts = vtk_to_numpy(epi.GetPoints().GetData())

        tag_epi = vtk_to_numpy(epi.GetCellData().GetArray('elemTag'))

        el_epi = vtk_to_numpy(epi.GetCellData().GetArray('fiber'))
        sheet_epi = vtk_to_numpy(epi.GetCellData().GetArray('sheet'))

        write_to_pts(f'{file_name}.pts', pts)
        write_to_elem(f'{file_name}.elem', epi, tag_epi)
        write_to_lon(f'{file_name}.lon', el_epi, sheet_epi)


if __name__ == '__main__':
    run()
