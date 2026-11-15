import unittest
import tkinter as tk
from types import SimpleNamespace
from gothic_editor.core.mesh import PreviewMesh
from gothic_editor.core.inventory_preview import rotation,inventory_mesh,number
from gothic_editor.ui.panels.viewer import ModelViewer


class InventoryTests(unittest.TestCase):
    def test_shared_fields_save_reload_and_emit_daedalus(self):
        import tempfile
        from pathlib import Path
        from gothic_editor.core.project import ProjectRepository
        from gothic_editor.core.properties_schema import schema_for
        with tempfile.TemporaryDirectory() as folder:
            repo=ProjectRepository();repo.create(Path(folder)/'p','Test')
            item=repo.create_item('scrolls')
            values={'inv_rotx':'90','inv_roty':'-45','inv_rotz':'180'}
            item=repo.edit(item,values)
            repo.open(repo.root)
            saved=repo.project_items[0]
            for key,value in values.items():
                self.assertEqual(saved.fields[key],value)
                self.assertIn(key+' = '+value+';',saved.text)
            keys={field.key for section in schema_for('scrolls').sections if section.key=='appearance' for field in section.fields}
            self.assertTrue(set(values)<=keys)

    def test_category_rotation_and_saved_offsets(self):
        self.assertEqual(rotation({},'potions'),(180,0,0))
        self.assertEqual(rotation({'inv_rotx':'-90','inv_rotz':'2 * 45'},'potions'),(90,0,90))
        self.assertEqual(rotation({},'onehand'),(-45,0,90))
        repo=SimpleNamespace(resource_revision=0,options_cache={('inventory_constants',0):{'angle':'45'}})
        self.assertEqual(number('ANGLE + 45',repo),90)
        with self.assertRaises(ValueError):number('unknown')

    def test_rotated_copy_preserves_geometry_source_uvs_and_materials(self):
        mesh=PreviewMesh([(1,2,3)],[],[(0,1)],['tex'],['mat'])
        result=inventory_mesh(mesh,(0,0,0))
        self.assertEqual(result.vertices,[(3,-2,-1)])
        self.assertEqual(mesh.vertices,[(1,2,3)])
        self.assertIs(result.uvs,mesh.uvs)
        self.assertIs(result.texture_names,mesh.texture_names)

    def test_inventory_axes_match_engine_matrix_rows_and_viewport(self):
        # Independent reference: Rx * Rz * Ry, followed by output X/Z swap
        # and conversion from Vulkan screen/depth to the preview rasterizer.
        import math
        def mul(a,b):return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        for angles in ((90,0,0),(0,90,0),(0,0,90),(203,47,-19)):
            x,y,z=map(math.radians,angles)
            cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
            m=mul(mul([[1,0,0],[0,cx,-sx],[0,sx,cx]],[[cz,-sz,0],[sz,cz,0],[0,0,1]]),[[cy,0,sy],[0,1,0],[-sy,0,cy]])
            vertices=[(1,0,0),(0,1,0),(0,0,1)]
            result=inventory_mesh(PreviewMesh(vertices,[]),angles)
            for vertex,actual in zip(vertices,result.vertices):
                v=[sum(row[i]*vertex[i] for i in range(3)) for row in m]
                for a,b in zip(actual,(v[2],-v[1],-v[0])):self.assertAlmostEqual(a,b)
        upright=inventory_mesh(PreviewMesh([(0,0,0),(0,10,0)],[]),rotation({},'potions'))
        self.assertGreater(upright.vertices[1][1],upright.vertices[0][1])

    def test_z_up_source_potion_is_upright_with_y_rotation_like_user_model(self):
        import tempfile
        from pathlib import Path
        from gothic_editor.core.model_export import geometry_3ds
        from gothic_editor.core.model_preview import load_model_preview
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'potion.3ds'
            path.write_bytes(geometry_3ds([(0,0,0),(0,0,20),(2,0,0)],[(0,1,2)]))
            original=path.read_bytes()
            preview=load_model_preview(path,Path(directory),with_textures=False)
            self.assertEqual(preview.mesh.vertices[1],(0,20,0))
            result=inventory_mesh(preview.mesh,rotation({'inv_roty':'45'},'potions'))
            self.assertAlmostEqual(result.vertices[1][0],0)
            self.assertAlmostEqual(result.vertices[1][1],20)
            self.assertEqual(path.read_bytes(),original)


class InventoryWidgetTests(unittest.TestCase):
    def test_single_texture_toggle_and_inventory_lock_restore_camera(self):
        root=tk.Tk()
        try:
            viewer=ModelViewer(root)
            self.assertEqual(len(viewer.toolbar.winfo_children()),2)
            viewer.texture_button.invoke()
            self.assertTrue(viewer.textured)
            viewer.texture_button.invoke()
            self.assertFalse(viewer.textured)
            viewer.set_mesh([(0,0,0),(1,0,0),(0,1,0)],[(0,1,2)])
            viewer.set_inventory_source(lambda:(180,0,0))
            camera=(viewer.angle_x,viewer.angle_y,viewer.zoom)
            viewer.inventory_button.invoke()
            self.assertTrue(viewer.inventory_locked)
            viewer.start_drag(SimpleNamespace(x=0,y=0))
            viewer.drag(SimpleNamespace(x=100,y=100))
            viewer.change_zoom(2)
            self.assertEqual((viewer.angle_x,viewer.angle_y,viewer.zoom),(0,0,1))
            viewer.inventory_button.invoke()
            self.assertEqual((viewer.angle_x,viewer.angle_y,viewer.zoom),camera)
            viewer.set_inventory_source(None)
            self.assertEqual(str(viewer.inventory_button['state']),'disabled')
        finally:root.destroy()
