-- sda_export.ms - Space Design Album: the scene as 3ds Max itself evaluates it.
--
-- 3ds Max 2016 or newer. Open the scene, then  Scripting > Run Script...  and pick this file.
-- Writes next to the scene (the scene itself is not changed):
--     <scene>.sda.json   every object: name, parent, classes, modifiers (on / off), hidden / frozen / renderable,
--                        layer, material and sub-materials by ID, transform, world bounding box, sign texts
--     <scene>.sda.bin    world-space triangle meshes after ALL modifiers (Edit Poly, Symmetry, FFD, Shell,
--                        FloorGenerator ...): float32 x y z per vertex, int32 a b c per face, uint16 material ID per face
-- The agent takes walls, boxes, floors and furniture sizes from these files instead of guessing what the modifiers
-- did, and checks the album against them (sda.py audit).

(
	fn sdaEsc s =
	(
		s = s as string
		local r = ""
		for i = 1 to s.count do
		(
			local c = s[i]
			if c == "\"" then r += "\\\""
			else if c == "\\" then r += "\\\\"
			else if c == "\n" then r += "\\n"
			else if c == "\r" then r += "\\r"
			else if c == "\t" then r += "\\t"
			else r += c
		)
		r
	)

	fn sdaStr s = ("\"" + (sdaEsc s) + "\"")
	fn sdaNum v = (formattedPrint (v as float) format:".4f")
	fn sdaBool b = (if b == true then "true" else "false")
	fn sdaP3 p = ("[" + (sdaNum p.x) + "," + (sdaNum p.y) + "," + (sdaNum p.z) + "]")

	fn sdaMaterial m =
	(
		if m == undefined then "null" else
		(
			local s = "{\"name\":" + (sdaStr m.name) + ",\"class\":" + (sdaStr (classOf m)) + ",\"subs\":["
			if classOf m == Multimaterial do
			(
				local ids = m.materialIDList
				local mats = m.materialList
				local first = true
				for i = 1 to mats.count do
				(
					local sm = mats[i]
					if sm != undefined do
					(
						if not first do s += ","
						first = false
						s += "[" + ((ids[i]) as string) + "," + (sdaStr sm.name) + "]"
					)
				)
			)
			s + "]}"
		)
	)

	fn sdaExport =
	(
		if maxFileName == "" do
		(
			messageBox "Откройте сцену (.max) и запустите скрипт ещё раз." title:"Space Design Album"
			return false
		)
		local base = maxFilePath + (getFilenameFile maxFileName)
		local jpath = base + ".sda.json"
		local bpath = base + ".sda.bin"
		local js = undefined
		try (js = createFile jpath encoding:#utf8 writeBOM:false) catch (js = createFile jpath)
		local bs = fopen bpath "wb"
		local mmPerUnit = 1.0 / (units.decodeValue "1mm")
		format "{\"format\":\"sda-export\",\"version\":1,\"scene\":%,\"max_version\":%,\"units\":{\"system\":%,\"scale\":%,\"mm_per_unit\":%},\"nodes\":[\n" (sdaStr maxFileName) ((maxVersion())[1]) (sdaStr units.SystemType) (sdaNum units.SystemScale) (sdaNum mmPerUnit) to:js
		local all = objects as array
		local n = all.count
		local done = 0
		local faces = 0
		progressStart "Space Design Album: выгрузка сцены"
		for i = 1 to n do
		(
			local o = all[i]
			if not (progressUpdate (100.0 * i / n)) do exit
			local meshInfo = "null"
			local isGeo = false
			try (isGeo = (superClassOf o == GeometryClass) and (classOf o != TargetObject) and (canConvertTo o TriMeshGeometry)) catch (isGeo = false)
			if isGeo do
			(
				local m = undefined
				try (m = snapshotAsMesh o) catch (m = undefined)
				if m != undefined do
				(
					local nv = m.numverts
					local nf = m.numfaces
					local off = ftell bs
					for k = 1 to nv do
					(
						local p = getVert m k
						WriteFloat bs p.x
						WriteFloat bs p.y
						WriteFloat bs p.z
					)
					for k = 1 to nf do
					(
						local f = getFace m k
						WriteLong bs ((f.x as integer) - 1) #signed
						WriteLong bs ((f.y as integer) - 1) #signed
						WriteLong bs ((f.z as integer) - 1) #signed
					)
					for k = 1 to nf do WriteShort bs (getFaceMatID m k) #unsigned
					meshInfo = "[" + (off as string) + "," + (nv as string) + "," + (nf as string) + "]"
					faces += nf
					try (delete m) catch ()
				)
			)
			local mods = ""
			for j = 1 to o.modifiers.count do
			(
				local md = o.modifiers[j]
				if j > 1 do mods += ","
				mods += "[" + (sdaStr (classOf md)) + "," + (sdaStr md.name) + "," + (sdaBool md.enabled) + "," + (sdaBool md.enabledInRenders) + "]"
			)
			local par = "null"
			if o.parent != undefined do par = sdaStr o.parent.name
			local bb = nodeGetBoundingBox o (matrix3 1)
			local tm = o.transform
			local lay = o.layer
			local txt = "null"
			try (if classOf o.baseObject == text do txt = "[" + (sdaStr o.baseObject.text) + "," + (sdaStr o.baseObject.font) + "]") catch ()
			local s = "{\"h\":" + (o.handle as string) + ",\"n\":" + (sdaStr o.name) + ",\"p\":" + par
			s += ",\"cls\":" + (sdaStr (classOf o.baseObject)) + ",\"top\":" + (sdaStr (classOf o)) + ",\"sup\":" + (sdaStr (superClassOf o))
			s += ",\"mods\":[" + mods + "]"
			s += ",\"hidden\":" + (sdaBool o.isHidden) + ",\"node_hidden\":" + (sdaBool o.isNodeHidden)
			s += ",\"frozen\":" + (sdaBool o.isFrozen) + ",\"renderable\":" + (sdaBool o.renderable)
			s += ",\"group_head\":" + (sdaBool (isGroupHead o)) + ",\"group_member\":" + (sdaBool (isGroupMember o))
			s += ",\"layer\":" + (sdaStr lay.name) + ",\"layer_hidden\":" + (sdaBool lay.isHidden) + ",\"layer_renderable\":" + (sdaBool lay.renderable)
			s += ",\"mat\":" + (sdaMaterial o.material)
			s += ",\"tm\":[" + (sdaP3 tm.row1) + "," + (sdaP3 tm.row2) + "," + (sdaP3 tm.row3) + "," + (sdaP3 tm.row4) + "]"
			s += ",\"bb\":[" + (sdaP3 bb[1]) + "," + (sdaP3 bb[2]) + "]"
			s += ",\"text\":" + txt + ",\"mesh\":" + meshInfo + "}"
			if done > 0 do format ",\n" to:js
			format "%" s to:js
			done += 1
		)
		progressEnd()
		format "\n],\"count\":%,\"faces\":%}\n" done faces to:js
		close js
		fclose bs
		messageBox ("Готово: " + (done as string) + " объектов, " + (faces as string) + " треугольников.\n\nОтправьте агенту оба файла рядом со сценой:\n" + jpath + "\n" + bpath) title:"Space Design Album"
		true
	)

	sdaExport()
)
