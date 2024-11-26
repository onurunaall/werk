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

import vtk

from vtk_opencarp_helper_methods.vtk_methods.converters import convert_point_to_cell_data
from vtk_opencarp_helper_methods.vtk_methods.exporting import vtk_xml_unstructured_grid_writer


def ra_calculate_gradient(args, model, job):
    name_list = ['phi', 'r', 'v', 'ab', 'w']

    # change the result of Laplace from points data to cell data

    model_with_cell_data = convert_point_to_cell_data(model)

    for var in name_list:
        print('Calculating the gradient of ' + str(var) + '...')
        if var == 'phi':
            # using the vtkGradientFilter to calculate the gradient
            if args.mesh_type == "vol":
                gradientFilter = vtk.vtkGradientFilter()
                gradientFilter.SetInputData(model_with_cell_data)
                gradientFilter.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS,
                                                      "phie_" + str(var))
                gradientFilter.SetResultArrayName('grad_' + str(var))
                gradientFilter.Update()
                RA_gradient = gradientFilter.GetOutput()
            else:
                normalFilter = vtk.vtkPolyDataNormals()
                normalFilter.SetInputData(model_with_cell_data)
                normalFilter.ComputeCellNormalsOn()
                normalFilter.ComputePointNormalsOff()
                normalFilter.SplittingOff()
                normalFilter.Update()
                RA_gradient = normalFilter.GetOutput()
                RA_gradient.GetCellData().GetArray("Normals").SetName('grad_' + str(var))
        else:
            gradientFilter = vtk.vtkGradientFilter()
            gradientFilter.SetInputData(RA_gradient)
            gradientFilter.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS,
                                                  "phie_" + str(var))
            gradientFilter.SetResultArrayName('grad_' + str(var))
            gradientFilter.Update()
            RA_gradient = gradientFilter.GetOutput()

    print('Calculating the gradient of ' + str(var) + '... Done!')

    output = vtk.vtkUnstructuredGrid()
    output.DeepCopy(RA_gradient)

    if args.debug == 1:
        # write
        simid = job.ID + "/gradient"
        try:
            os.makedirs(simid)
        except OSError:
            print(f"Creation of the directory {simid} failed")
        else:
            print(f"Successfully created the directory {simid} ")
        # write the file as vtk 
        vtk_xml_unstructured_grid_writer(simid + "/RA_with_lp_res_gradient.vtu", output)
    return output
