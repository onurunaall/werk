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

import os

import numpy as np
import vtk
from scipy.spatial import cKDTree
from vtk.numpy_interface import dataset_adapter as dsa

from vtk_opencarp_helper_methods.AugmentA_methods.vtk_operations import vtk_thr
from vtk_opencarp_helper_methods.vtk_methods.converters import vtk_to_numpy, convert_point_to_cell_data
from vtk_opencarp_helper_methods.vtk_methods.exporting import vtk_xml_unstructured_grid_writer
from vtk_opencarp_helper_methods.vtk_methods.filters import apply_vtk_geom_filter, get_vtk_geom_filter_port, \
    clean_polydata, generate_ids, get_cells_with_ids
from vtk_opencarp_helper_methods.vtk_methods.finder import find_closest_point
from vtk_opencarp_helper_methods.vtk_methods.init_objects import init_connectivity_filter, ExtractionModes
from vtk_opencarp_helper_methods.vtk_methods.reader import smart_reader
from vtk_opencarp_helper_methods.writer import write_to_dat

vtk_version = vtk.vtkVersion.GetVTKSourceVersion().split()[-1].split('.')[0]


def low_vol_LAT(args, path):
    # Read mesh
    meshname = f'{args.mesh}_fibers/result_LA/LA_bilayer_with_fiber_with_data_um'  # in um
    model = smart_reader(f'{meshname}.vtk')

    bilayer_n_cells = model.GetNumberOfCells()

    # Transfer lat and bipolar voltage from points to elements
    model = convert_point_to_cell_data(model, ["bi"], ["lat"])

    # Create Points and Cells ids
    model = generate_ids(model, "Global_ids", "Global_ids", True)

    # Compute elements centroids
    filter_cell_centers = vtk.vtkCellCenters()
    filter_cell_centers.SetInputData(model)
    filter_cell_centers.Update()
    centroids = vtk_to_numpy(filter_cell_centers.GetOutput().GetPoints().GetData())

    # Low voltage in the model
    low_vol = vtk_thr(model, 1, "CELLS", "bi", args.low_vol_thr)
    low_vol_ids = vtk_to_numpy(low_vol.GetCellData().GetArray('Global_ids')).astype(int)

    if args.debug:

        meshbasename = args.mesh.split("/")[-1]
        debug_dir = f'{args.init_state_dir}/{meshbasename}/debug'
        try:
            os.makedirs(debug_dir)
        except OSError:
            print(f"Creation of the directory {debug_dir} failed")
        else:
            print(f"Successfully created the directory {debug_dir} ")

        vtk_xml_unstructured_grid_writer(f'{debug_dir}/low_vol.vtu', low_vol)
    # Endo

    endo = vtk_thr(apply_vtk_geom_filter(model), 1, "CELLS", "elemTag", 10)

    if args.debug:
        vtk_xml_unstructured_grid_writer(f'{debug_dir}/endo.vtu', endo)
    # Get point LAT map in endocardium
    LAT_endo = vtk_to_numpy(endo.GetPointData().GetArray('lat'))
    endo_ids = vtk_to_numpy(endo.GetCellData().GetArray('Global_ids')).astype(int)
    endo_pts = vtk_to_numpy(endo.GetPoints().GetData())

    # Get elements LAT map in endocardium
    LAT_map = vtk_to_numpy(endo.GetCellData().GetArray('lat'))

    # Extract "healthy" high voltage endocardium
    not_low_volt_endo = vtk_thr(endo, 0, "POINTS", "bi", 0.5 + 0.01)
    LAT_not_low_volt = vtk_to_numpy(not_low_volt_endo.GetPointData().GetArray('lat'))
    not_low_volt_endo_pts = vtk_to_numpy(not_low_volt_endo.GetPoints().GetData())
    not_low_volt_ids = vtk_to_numpy(
        not_low_volt_endo.GetPointData().GetArray('Global_ids')).astype(int)

    if args.debug:
        vtk_xml_unstructured_grid_writer(f'{debug_dir}/not_low_volt_endo.vtu', not_low_volt_endo)
    # Extract LA wall from SSM to be sure that no veins or LAA is included when selecting the earliest activated point
    if args.SSM_fitting:
        LA_wall = smart_reader(args.SSM_basename + '/LA_wall.vtk')
        LA_wall_pt_ids = vtk_to_numpy(LA_wall.GetPointData().GetArray('PointIds'))

        # See create_SSM_instance standalone to create LA_fit.obj
        reader = vtk.vtkOBJReader()
        reader.SetFileName(f'{args.mesh}/LA_fit.obj')
        reader.Update()
        LA_fit = reader.GetOutput()

        LA_fit_wall_pts = vtk_to_numpy(LA_fit.GetPoints().GetData())[LA_wall_pt_ids, :] * 1000

        tree = cKDTree(not_low_volt_endo_pts)

        dd, ii = tree.query(LA_fit_wall_pts)
    else:
        tree = cKDTree(not_low_volt_endo_pts)
        dd, ii = tree.query(endo_pts)

    healthy_endo = not_low_volt_endo  # vtk_thr(not_low_volt_endo,0,"POINTS","CV_mag", args.low_CV_thr)
    LAT_healthy = vtk_to_numpy(healthy_endo.GetPointData().GetArray('lat'))
    healthy_ids = vtk_to_numpy(healthy_endo.GetPointData().GetArray('Global_ids')).astype(int)

    if args.max_LAT_pt == "max":

        # Selecting the location of earliest/latest activation as the very first activated map point 
        # or electrogram point can be error-prone since it can happen that there is a single point which was annotated too early/late
        # Latest activated point is the center of mass of the 97.5 percentile of LAT

        perc_975 = np.percentile(LAT_not_low_volt[ii], 97.5)

        ids = np.where(LAT_not_low_volt[ii] >= perc_975)[0]

        max_pt = np.mean(not_low_volt_endo_pts[ii][ids], axis=0)

        args.max_LAT_id = find_closest_point(not_low_volt_endo, max_pt)
        max_pt = np.array(not_low_volt_endo.GetPoint(args.max_LAT_id))
        args.LaAT = np.max(LAT_not_low_volt)

        # Earliest activated point is the center of mass of the 2.5 percentile of LAT
        perc_25 = np.percentile(LAT_not_low_volt[ii], 2.5)

        ids = np.where(LAT_not_low_volt[ii] <= perc_25)[0]

        stim_pt = np.mean(not_low_volt_endo_pts[ii][ids], axis=0)

        stim_pt_id = find_closest_point(not_low_volt_endo, stim_pt)
        stim_pt = np.array(not_low_volt_endo.GetPoint(stim_pt_id))
        min_LAT = np.min(LAT_not_low_volt[ii])

        # Comp
        fit_LAT = []
        steps = list(np.arange(min_LAT, args.LaAT, args.step))
        for i in range(1, len(steps)):
            fit_LAT.append(steps[i] - min_LAT)

        fit_LAT.append(args.LaAT - min_LAT)

    # Before proceeding with the iterative fitting of the clinical LAT, we detect the nodes 
    # with an earlier activation than the neighboring vertices and mark them as wrong annotations
    el_to_clean, el_border = areas_to_clean(endo, args, min_LAT, stim_pt)

    return bilayer_n_cells, low_vol_ids, endo, endo_ids, centroids, LAT_map - min_LAT, min_LAT, el_to_clean, el_border, stim_pt, fit_LAT, healthy_endo


def areas_to_clean(endo, args, min_LAT, stim_pt):
    # Really fine LAT bands with time step of 5 ms
    steps = list(np.arange(min_LAT, args.LaAT, 5))
    steps.append(args.LaAT)
    el_to_clean = []
    el_border = []
    tot_el_to_clean = np.array([], dtype=int)

    meshNew = dsa.WrapDataObject(endo)
    print("Starting creation of bands ... ")
    for i in range(1, len(steps)):

        # Extract LAT band from min LAT to step i and remove all areas not connected with EAP
        band = vtk_thr(endo, 2, "CELLS", "lat", min_LAT, steps[i])

        b_ids = vtk_to_numpy(band.GetCellData().GetArray('Global_ids')).astype(int)

        connect = init_connectivity_filter(band, ExtractionModes.CLOSEST_POINT, closest_point=stim_pt)
        largest_band = connect.GetOutput()

        l_b_ids = vtk_to_numpy(largest_band.GetCellData().GetArray('Global_ids')).astype(int)

        if len(b_ids) > len(l_b_ids):
            cell_diff = set()

            # Find all elements which are not belonging to the clean band
            el_diff = np.setdiff1d(b_ids, l_b_ids)
            b_ids = list(b_ids)
            for el in el_diff:
                cell_diff.add(b_ids.index(el))

            geo_port, _geo_filter = get_vtk_geom_filter_port(get_cells_with_ids(band, cell_diff))

            # Mesh of all elements which are not belonging to the clean band
            el_removed = clean_polydata(geo_port, input_is_connection=True)

            # Compute centroids of all elements which are not belonging to the clean band
            filter_cell_centers = vtk.vtkCellCenters()
            filter_cell_centers.SetInputData(largest_band)
            filter_cell_centers.Update()
            centroids2 = filter_cell_centers.GetOutput().GetPoints()
            pts = vtk_to_numpy(centroids2.GetData())

            tree = cKDTree(pts)

            connect = init_connectivity_filter(el_removed, ExtractionModes.SPECIFIED_REGIONS)
            num = connect.GetNumberOfExtractedRegions()
            for n in range(num):
                connect.AddSpecifiedRegion(n)
                connect.Update()

                geo_port, _geo_filter = get_vtk_geom_filter_port(connect.GetOutputPort(), True)

                # Clean unused points
                surface = clean_polydata(geo_port, input_is_connection=True)

                filter_cell_centers = vtk.vtkCellCenters()
                filter_cell_centers.SetInputData(surface)
                filter_cell_centers.Update()
                centroids1 = filter_cell_centers.GetOutput().GetPoints()
                centroids1_array = vtk_to_numpy(centroids1.GetData())

                dd, ii = tree.query(centroids1_array, n_jobs=-1)

                # Set as elements to clean only if they are at least 1 um away from the biggest band
                if np.min(dd) > 1:
                    loc_el_to_clean = vtk_to_numpy(
                        surface.GetCellData().GetArray('Global_ids')).astype(int)

                    tot_el_to_clean = np.union1d(tot_el_to_clean, loc_el_to_clean)

                # delete added region id
                connect.DeleteSpecifiedRegion(n)
                connect.Update()

    print("Bands to clean ready ... ")

    idss = np.zeros((endo.GetNumberOfCells(),))
    idss[tot_el_to_clean] = 1

    meshNew.CellData.append(idss, "idss")

    endo_clean = vtk_thr(meshNew.VTKObject, 1, "CELLS", "idss", 0)

    el_cleaned = vtk_to_numpy(endo_clean.GetCellData().GetArray('Global_ids')).astype(int)

    endo_to_interpolate = vtk_thr(meshNew.VTKObject, 0, "CELLS", "idss", 1)

    filter_cell_centers = vtk.vtkCellCenters()
    filter_cell_centers.SetInputData(endo_clean)
    filter_cell_centers.Update()
    centroids2 = filter_cell_centers.GetOutput().GetPoints()
    pts = vtk_to_numpy(centroids2.GetData())

    tree = cKDTree(pts)

    # Find elements at the boundary of the areas to clean, which are gonna be used for the fitting of the conductivities
    connect = init_connectivity_filter(endo_to_interpolate, ExtractionModes.SPECIFIED_REGIONS)
    num = connect.GetNumberOfExtractedRegions()
    for n in range(num):
        connect.AddSpecifiedRegion(n)
        connect.Update()

        geo_port, _geo_filter = get_vtk_geom_filter_port(connect.GetOutputPort(), True)

        # Clean unused points
        surface = clean_polydata(geo_port, input_is_connection=True)

        loc_el_to_clean = vtk_to_numpy(surface.GetCellData().GetArray('Global_ids')).astype(int)

        el_to_clean.append(np.unique(loc_el_to_clean))

        filter_cell_centers = vtk.vtkCellCenters()
        filter_cell_centers.SetInputData(surface)
        filter_cell_centers.Update()
        centroids1 = filter_cell_centers.GetOutput().GetPoints()
        centroids1_array = vtk_to_numpy(centroids1.GetData())

        dd, ii = tree.query(centroids1_array, n_jobs=-1)  # Find distance to endo_clean pts

        el_border.append(np.unique(el_cleaned[ii]))  # Give id of the closest point to the endo_clean

        # delete added region id
        connect.DeleteSpecifiedRegion(n)
        connect.Update()

    if args.debug:

        meshbasename = args.mesh.split("/")[-1]
        debug_dir = f'{args.init_state_dir}/{meshbasename}/debug'
        try:
            os.makedirs(debug_dir)
        except OSError:
            print(f"Creation of the directory {debug_dir} failed")
        else:
            print(f"Successfully created the directory {debug_dir} ")

        el_border_array = np.concatenate(el_border)  # convert to linear array
        border = np.zeros((endo.GetNumberOfCells(),))
        border[el_border_array] = 1
        meshNew.CellData.append(border, "border")

        vtk_xml_unstructured_grid_writer(f'{debug_dir}/endo_with_clean_tag.vtu', meshNew.VTKObject)
    return el_to_clean, el_border


def create_regele(endo, args):
    # Low voltage in the model
    low_vol = vtk_thr(endo, 1, "CELLS", "bi", args.low_vol_thr)
    low_vol_ids = vtk_to_numpy(low_vol.GetCellData().GetArray('Global_ids')).astype(int)
    not_low_volt_endo = vtk_thr(endo, 0, "POINTS", "bi", 0.5 + 0.01)

    f_slow_conductive = f"{args.init_state_dir}/{args.mesh.split('/')[-1]}/elems_slow_conductive"
    file = open(f_slow_conductive + '.regele', 'w')
    file.write(str(len(low_vol_ids)) + '\n')
    for i in low_vol_ids:
        file.write(str(i) + '\n')
    file.close()

    print('Regele file done ...')


def low_CV(model, low_CV_thr, meshfold):
    low_CV = vtk_thr(model, 1, "CELLS", "CV_mag", low_CV_thr)

    low_CV_ids = vtk_to_numpy(low_CV.GetCellData().GetArray('Global_ids')).astype(int)

    low_CV_c = vtk_to_numpy(low_CV.GetCellData().GetArray('CV_mag')) / 1000

    low_sigma = low_CV_c ** 2

    sigma = np.ones((model.GetNumberOfCells(),))

    sigma[low_CV_ids] = 0.6 ** 2  # low_sigma
    write_to_dat(meshfold + '/low_CV.dat', sigma)


def get_EAP(path_mod, path_fib):
    model = smart_reader(path_mod)
    mod_fib = smart_reader(path_fib)

    mod_fib = generate_ids(mod_fib, "Global_ids", "Global_ids", True)
    LA_MV = vtk_thr(mod_fib, 1, "CELLS", "elemTag", 2)
    LAT_map = vtk_to_numpy(model.GetPointData().GetArray('LAT'))

    LA_MV_ids = vtk_to_numpy(LA_MV.GetPointData().GetArray('Global_ids')).astype(int)

    print(LA_MV_ids[np.argmin(LAT_map[LA_MV_ids])])
    stim_pt = model.GetPoint(LA_MV_ids[np.argmin(LAT_map[LA_MV_ids])])

    return stim_pt