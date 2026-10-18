static int dsi_panel_parse_bl_config(struct dsi_panel *panel)
{
	int rc = 0;
	u32 val = 0;
	const char *bl_type;
	const char *data;
	struct dsi_parser_utils *utils = &panel->utils;
	char *bl_name;

	if (!strcmp(panel->type, "primary"))
		bl_name = "qcom,mdss-dsi-bl-pmic-control-type";
	else
		bl_name = "qcom,mdss-dsi-sec-bl-pmic-control-type";

	bl_type = utils->get_property(utils->data, bl_name, NULL);
	if (!bl_type) {
		panel->bl_config.type = DSI_BACKLIGHT_UNKNOWN;
	} else if (!strcmp(bl_type, "bl_ctrl_pwm")) {
		panel->bl_config.type = DSI_BACKLIGHT_PWM;
	} else if (!strcmp(bl_type, "bl_ctrl_wled")) {
		panel->bl_config.type = DSI_BACKLIGHT_WLED;
	} else if (!strcmp(bl_type, "bl_ctrl_dcs")) {
		panel->bl_config.type = DSI_BACKLIGHT_DCS;
/*added by webber for task 32828: brightness can be modified--start*/
	} else if (!strcmp(bl_type, "bl_ctrl_gpio")) {
		panel->bl_config.type = DSI_BACKLIGHT_GPIO;
		panel->bl_config.bklt_brightness_gpio[0] = utils->get_named_gpio(utils->data,
				"qcom,mdss-dsi-bklight-gpio1", 0);
		if (gpio_is_valid(panel->bl_config.bklt_brightness_gpio[0])){
			pr_info("%s: qcom,mdss-dsi-bklight-gpio1 specified\n", __func__);

		rc = gpio_request(panel->bl_config.bklt_brightness_gpio[0],"bklight-gpio1");
		if (rc)
			pr_err("request mdss-dsi-bklight-gpio1 failed, rc=%d\n",rc);
		}

		panel->bl_config.bklt_brightness_gpio[1] = utils->get_named_gpio(utils->data,
				"qcom,mdss-dsi-bklight-gpio2", 0);
		if (gpio_is_valid(panel->bl_config.bklt_brightness_gpio[1])){
			pr_info("%s: qcom,mdss-dsi-bklight-gpio2  specified\n", __func__);

		rc = gpio_request(panel->bl_config.bklt_brightness_gpio[1],"bklight-gpio2");
		if (rc)
			pr_err("request mdss-dsi-bklight-gpio2 failed, rc=%d\n",rc);
		}

		panel->bl_config.bklt_brightness_gpio[2] = utils->get_named_gpio(utils->data,
				"qcom,mdss-dsi-bklight-gpio3", 0);
		if (gpio_is_valid(panel->bl_config.bklt_brightness_gpio[2])){
			pr_err("%s: qcom,mdss-dsi-bklight-gpio3  specified\n", __func__);

		rc = gpio_request(panel->bl_config.bklt_brightness_gpio[2],"bklight-gpio3");
		if (rc)
			pr_err("request mdss-dsi-bklight-gpio3 failed, rc=%d\n",rc);
		}
	/*added by webber for task 32828: brightness can be modified--end*/
	} else if (!strcmp(bl_type, "bl_ctrl_external")) {
		panel->bl_config.type = DSI_BACKLIGHT_EXTERNAL;
	} else {
		DSI_DEBUG("[%s] bl-pmic-control-type unknown-%s\n",
			 panel->name, bl_type);
		panel->bl_config.type = DSI_BACKLIGHT_UNKNOWN;
	}

	data = utils->get_property(utils->data, "qcom,bl-update-flag", NULL);
	if (!data) {
		panel->bl_config.bl_update = BL_UPDATE_NONE;
	} else if (!strcmp(data, "delay_until_first_frame")) {
		panel->bl_config.bl_update = BL_UPDATE_DELAY_UNTIL_FIRST_FRAME;
	} else {
		DSI_DEBUG("[%s] No valid bl-update-flag: %s\n",
						panel->name, data);
		panel->bl_config.bl_update = BL_UPDATE_NONE;
	}

	panel->bl_config.bl_scale = MAX_BL_SCALE_LEVEL;
	panel->bl_config.bl_scale_sv = MAX_SV_BL_SCALE_LEVEL;

	rc = utils->read_u32(utils->data, "qcom,mdss-dsi-bl-min-level", &val);
	if (rc) {
		DSI_DEBUG("[%s] bl-min-level unspecified, defaulting to zero\n",
			 panel->name);
		panel->bl_config.bl_min_level = 0;
	} else {
		panel->bl_config.bl_min_level = val;
	}

	rc = utils->read_u32(utils->data, "qcom,mdss-dsi-bl-max-level", &val);
	if (rc) {
		DSI_DEBUG("[%s] bl-max-level unspecified, defaulting to max level\n",
			 panel->name);
		panel->bl_config.bl_max_level = MAX_BL_LEVEL;
	} else {
		panel->bl_config.bl_max_level = val;
	}

	rc = utils->read_u32(utils->data, "qcom,mdss-brightness-max-level",
		&val);
	if (rc) {
		DSI_DEBUG("[%s] brigheness-max-level unspecified, defaulting to 255\n",
			 panel->name);
		panel->bl_config.brightness_max_level = 255;
	} else {
		panel->bl_config.brightness_max_level = val;
	}

	rc = utils->read_u32(utils->data, "qcom,mdss-dsi-bl-ctrl-dcs-subtype",
		&val);
	if (rc) {
		DSI_DEBUG("[%s] bl-ctrl-dcs-subtype, defautling to zero\n",
			panel->name);
		panel->bl_config.bl_dcs_subtype = 0;
	} else {
		panel->bl_config.bl_dcs_subtype = val;
	}

	if (panel->bl_config.type == DSI_BACKLIGHT_PWM) {
		rc = dsi_panel_parse_bl_pwm_config(panel);
		if (rc) {
			DSI_ERR("[%s] failed to parse pwm config, rc=%d\n",
			       panel->name, rc);
			goto error;
		}
	}

	panel->bl_config.en_gpio = utils->get_named_gpio(utils->data,
					      "qcom,platform-bklight-en-gpio",
					      0);
	if (!gpio_is_valid(panel->bl_config.en_gpio)) {
		if (panel->bl_config.en_gpio == -EPROBE_DEFER) {
			DSI_DEBUG("[%s] failed to get bklt gpio, rc=%d\n",
					panel->name, rc);
			rc = -EPROBE_DEFER;
			goto error;
		} else {
			DSI_DEBUG("[%s] failed to get bklt gpio, rc=%d\n",
					 panel->name, rc);
			rc = 0;
			goto error;
		}
	}

error:
	return rc;
}

void dsi_dsc_pclk_param_calc(struct msm_display_dsc_info *dsc, int intf_width)
{
	int slice_per_pkt, slice_per_intf;
	int bytes_in_slice, total_bytes_per_intf;

	if (!dsc || !dsc->slice_width || !dsc->slice_per_pkt ||
	    (intf_width < dsc->slice_width)) {
		DSI_ERR("invalid input, intf_width=%d slice_width=%d\n",
			intf_width, dsc ? dsc->slice_width : -1);
		return;
	}

	slice_per_pkt = dsc->slice_per_pkt;
	slice_per_intf = DIV_ROUND_UP(intf_width, dsc->slice_width);
