#!/usr/bin/env python3

# from scipy import spatial
# import function
# from sklearn.neighbors import NearestNeighbors
import argparse

import numpy as np
# from glob import glob
# import pandas as pd
import vtk
from scipy.spatial import cKDTree
from vtk.numpy_interface import dataset_adapter as dsa

from vtk_opencarp_helper_methods.openCARP.exporting import write_to_pts, write_to_elem, write_to_lon
from vtk_opencarp_helper_methods.vtk_methods.converters import vtk_to_numpy, numpy_to_vtk
from vtk_opencarp_helper_methods.vtk_methods.exporting import vtk_unstructured_grid_writer
from vtk_opencarp_helper_methods.vtk_methods.filters import apply_vtk_geom_filter, get_vtk_geom_filter_port, vtk_append

parser = argparse.ArgumentParser(description='Create Right Atrium.')

parser.add_argument('--mesh',
                    type=str,
                    default="../../../data/20220203/20220203_res_fibers/result_RA",
                    help='path to meshname')
parser.add_argument('--scale',
                    type=float,
                    default=1,
                    help='set 1 when the mesh is in mm or 1000 if it is in microns')

args = parser.parse_args()


def run(args):
    reader = vtk.vtkUnstructuredGridReader()
    reader.SetFileName(args.mesh + "/RA_CT_PMs.vtk")
    reader.Update()
    ra_endo = reader.GetOutput()

    reader = vtk.vtkUnstructuredGridReader()
    reader.SetFileName(args.mesh + "/RA_epi_with_fiber.vtk")
    reader.Update()
    ra_epi = reader.GetOutput()

    endo = move_surf_along_normals(ra_endo, 0.1 * args.scale,
                                   1)  # # Warning: set -1 if pts normals are pointing outside

    vtk_unstructured_grid_writer(args.mesh + "/RA_endo_with_fiber_moved.vtk", endo)
    bilayer = generate_bilayer(endo, ra_epi, 0.12 * args.scale)
    # bilayer = generate_bilayer(ra_endo, ra_epi)

    write_bilayer(bilayer)


def move_surf_along_normals(mesh, eps, direction):
    polydata = apply_vtk_geom_filter(mesh)

    normalGenerator = vtk.vtkPolyDataNormals()
    normalGenerator.SetInputData(polydata)
    normalGenerator.ComputeCellNormalsOff()
    normalGenerator.ComputePointNormalsOn()
    normalGenerator.ConsistencyOn()
    normalGenerator.SplittingOff()
    normalGenerator.Update()

    PointNormalArray = vtk_to_numpy(normalGenerator.GetOutput().GetPointData().GetNormals())
    atrial_points = vtk_to_numpy(polydata.GetPoints().GetData())

    atrial_points = atrial_points + eps * direction * PointNormalArray

    vtkPts = vtk.vtkPoints()
    vtkPts.SetData(numpy_to_vtk(atrial_points))
    polydata.SetPoints(vtkPts)

    mesh = vtk.vtkUnstructuredGrid()
    mesh.DeepCopy(polydata)

    return mesh


def generate_bilayer(endo, epi, max_dist=np.inf):
    geo_port, _geo_filter = get_vtk_geom_filter_port(endo)
    reverse = vtk.vtkReverseSense()
    reverse.ReverseCellsOn()
    reverse.ReverseNormalsOn()
    reverse.SetInputConnection(geo_port)
    reverse.Update()

    endo = vtk.vtkUnstructuredGrid()
    endo.DeepCopy(reverse.GetOutput())

    endo_pts = vtk_to_numpy(endo.GetPoints().GetData())
    epi_pts = vtk_to_numpy(epi.GetPoints().GetData())

    tree = cKDTree(epi_pts)
    dd, ii = tree.query(endo_pts, distance_upper_bound=max_dist, n_jobs=-1)

    endo_ids = np.where(dd != np.inf)[0]
    epi_ids = ii[endo_ids]
    lines = vtk.vtkCellArray()

    for i in range(len(endo_ids)):
        line = vtk.vtkLine()
        line.GetPointIds().SetId(0, i);
        line.GetPointIds().SetId(1, len(endo_ids) + i);
        lines.InsertNextCell(line)

    points = np.vstack((endo_pts[endo_ids], epi_pts[epi_ids]))
    polydata = vtk.vtkUnstructuredGrid()
    vtkPts = vtk.vtkPoints()
    vtkPts.SetData(numpy_to_vtk(points))
    polydata.SetPoints(vtkPts)
    polydata.SetCells(3, lines)

    fibers = np.zeros((len(endo_ids), 3), dtype="float32")
    fibers[:, 0] = 1

    tag = np.ones((len(endo_ids),), dtype=int)
    tag[:] = 100

    meshNew = dsa.WrapDataObject(polydata)
    meshNew.CellData.append(tag, "elemTag")
    meshNew.CellData.append(fibers, "fiber")
    fibers = np.zeros((len(endo_ids), 3), dtype="float32")
    fibers[:, 1] = 1
    meshNew.CellData.append(fibers, "sheet")

    bilayer = vtk_append([endo, epi, meshNew.VTKObject], True)

    return bilayer


# Creates VTK and CARP files: .pts, .lon, .elem
def write_bilayer(bilayer):
    file_name = args.mesh + "/RA_bilayer_with_fiber"
    vtk_unstructured_grid_writer(f"{file_name}.vtk", bilayer, store_binary=True)

    pts = vtk_to_numpy(bilayer.GetPoints().GetData())

    tag_epi = vtk.util.vtk_to_numpy(bilayer.GetCellData().GetArray('elemTag'))

    el_epi = vtk.util.vtk_to_numpy(bilayer.GetCellData().GetArray('fiber'))
    sheet_epi = vtk.util.vtk_to_numpy(bilayer.GetCellData().GetArray('sheet'))

    write_to_pts(f'{file_name}.pts', pts)
    write_to_elem(f'{file_name}.elem', bilayer, tag_epi)
    write_to_lon(f'{file_name}.lon', el_epi, sheet_epi)

    print('Generated Bilayer RA')


if __name__ == '__main__':
    run(args)
